#!/usr/bin/env python3
"""Tail Warp's local network log and emit normalized NDJSON usage events."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any


HEADER_RE = re.compile(r"^\[(?P<timestamp>[^\]]+)\]: (?P<kind>Request|Response)\b")
TARGET_HOST_FRAGMENT = "dataplane.rudderstack.com"
TARGET_PATH_FRAGMENT = '/v1/batch'
BLOCK_CREATION_EVENT = "Block Creation"
ALLOWED_EVENTS = {
    "AgentMode.CreatedAIBlock",
    "AIAutonomy.AutoexecutedRequestedCommand",
    "AgentMode.Code.SuggestedEditReceived",
    "AgentMode.Code.SuggestedEditResolved",
}


@dataclass
class BridgeState:
    offset: int = 0
    inode: int | None = None


@dataclass
class ProcessResult:
    bytes_processed: int
    records_seen: int
    events_emitted: int


@dataclass
class BridgeConfig:
    source_path: Path
    output_path: Path
    state_path: Path
    poll_interval: float
    once: bool


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_source_path() -> Path:
    return Path.home() / "Library/Application Support/dev.warp.Warp-Stable/warp_network.log"


def default_output_path() -> Path:
    return repo_root() / "tmp/warp-usage-events.ndjson"


def default_state_path() -> Path:
    return repo_root() / "tmp/warp-usage-bridge-state.json"


def parse_args(argv: list[str]) -> BridgeConfig:
    parser = argparse.ArgumentParser(
        description="Normalize Warp network log analytics batches into NDJSON."
    )
    parser.add_argument(
        "--source-path",
        default=os.environ.get("WARP_NETWORK_LOG_PATH", str(default_source_path())),
        help="Path to warp_network.log.",
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("WARP_USAGE_OUTPUT_PATH", str(default_output_path())),
        help="Path to the normalized NDJSON output file.",
    )
    parser.add_argument(
        "--state-path",
        default=os.environ.get("WARP_USAGE_STATE_PATH", str(default_state_path())),
        help="Path to the persisted bridge offset state file.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("WARP_USAGE_POLL_INTERVAL", "1.0")),
        help="Polling interval in seconds for tail mode.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process the currently available source data once, then exit.",
    )
    args = parser.parse_args(argv)

    return BridgeConfig(
        source_path=Path(args.source_path).expanduser(),
        output_path=Path(args.output_path).expanduser(),
        state_path=Path(args.state_path).expanduser(),
        poll_interval=args.poll_interval,
        once=args.once,
    )


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_state(path: Path) -> BridgeState:
    if not path.exists():
        return BridgeState()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError):
        return BridgeState()

    offset = data.get("offset")
    inode = data.get("inode")
    if not isinstance(offset, int):
        offset = 0
    if not isinstance(inode, int):
        inode = None
    return BridgeState(offset=offset, inode=inode)


def save_state(path: Path, state: BridgeState) -> None:
    ensure_parent(path)
    payload = {"offset": state.offset, "inode": state.inode}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def split_records(chunk: bytes) -> list[tuple[int, str]]:
    records: list[tuple[int, str]] = []
    current_lines: list[str] = []
    current_start = 0
    consumed = 0

    for raw_line in chunk.splitlines(keepends=True):
        line = raw_line.decode("utf-8", errors="replace")
        if HEADER_RE.match(line):
            if current_lines:
                records.append((current_start, "".join(current_lines)))
            current_lines = [line]
            current_start = consumed
        elif current_lines:
            current_lines.append(line)
        consumed += len(raw_line)

    if current_lines:
        records.append((current_start, "".join(current_lines)))

    return records


def process_record(record_text: str, *, allow_incomplete: bool) -> tuple[str, list[dict[str, Any]]]:
    lines = record_text.splitlines()
    if not lines:
        return ("skip", [])

    header_match = HEADER_RE.match(lines[0])
    if not header_match or header_match.group("kind") != "Request":
        return ("skip", [])

    if TARGET_HOST_FRAGMENT not in record_text or TARGET_PATH_FRAGMENT not in record_text:
        return ("skip", [])

    if "\nBody " not in record_text:
        return ("incomplete", []) if allow_incomplete else ("skip", [])

    body_text = record_text.split("\nBody ", 1)[1]
    try:
        request_body = json.loads(body_text)
    except JSONDecodeError:
        return ("incomplete", []) if allow_incomplete else ("skip", [])

    return ("emit", normalize_batch_payload(request_body))


def normalize_batch_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    batch = payload.get("batch")
    if not isinstance(batch, list):
        return []

    normalized_events: list[dict[str, Any]] = []
    for raw_item in batch:
        if not isinstance(raw_item, dict):
            continue
        normalized = normalize_event(raw_item)
        if normalized is not None:
            normalized_events.append(normalized)

    return normalized_events


def normalize_event(event: dict[str, Any]) -> dict[str, Any] | None:
    event_name = event.get("event")
    if not isinstance(event_name, str):
        return None

    properties = event.get("properties")
    if not isinstance(properties, dict):
        properties = {}

    payload = properties.get("payload")
    if not isinstance(payload, dict):
        payload = {}

    if event_name == BLOCK_CREATION_EVENT:
        if not payload.get("is_in_agent_view"):
            return None
    elif event_name not in ALLOWED_EVENTS:
        return None

    normalized: dict[str, Any] = {
        "service_name": "warp",
        "source": "warp-network-log",
        "event": event_name,
    }

    timestamp = event.get("originalTimestamp")
    if isinstance(timestamp, str):
        normalized["timestamp"] = timestamp

    release_mode = properties.get("release_mode")
    if isinstance(release_mode, str):
        normalized["release_mode"] = release_mode

    amplitude = deep_get(event, "integrations", "Amplitude")
    if isinstance(amplitude, dict):
        session_id = amplitude.get("session_id")
        if isinstance(session_id, (int, float)):
            normalized["session_id"] = int(session_id)

    copy_if_present(
        payload,
        normalized,
        (
            "conversation_id",
            "client_exchange_id",
            "server_output_id",
            "model_id",
            "time_to_first_token_ms",
            "time_to_last_token_ms",
            "was_user_facing_error",
            "reason",
            "terminal_session_id",
        ),
    )

    return normalized


def copy_if_present(source: dict[str, Any], destination: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        destination[key] = value


def deep_get(source: dict[str, Any], *path: str) -> Any:
    current: Any = source
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def append_events(output_path: Path, events: list[dict[str, Any]]) -> None:
    if not events:
        return

    ensure_parent(output_path)
    with output_path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, separators=(",", ":"), sort_keys=True))
            handle.write("\n")


def process_available_records(config: BridgeConfig) -> ProcessResult:
    ensure_parent(config.output_path)
    ensure_parent(config.state_path)

    if not config.source_path.exists():
        raise FileNotFoundError(config.source_path)

    state = load_state(config.state_path)
    stat_result = config.source_path.stat()

    if state.inode != stat_result.st_ino or stat_result.st_size < state.offset:
        state = BridgeState(offset=0, inode=stat_result.st_ino)
    else:
        state.inode = stat_result.st_ino

    with config.source_path.open("rb") as handle:
        handle.seek(state.offset)
        chunk = handle.read()

    if not chunk:
        save_state(config.state_path, state)
        return ProcessResult(bytes_processed=0, records_seen=0, events_emitted=0)

    last_newline = chunk.rfind(b"\n")
    if last_newline < 0:
        return ProcessResult(bytes_processed=0, records_seen=0, events_emitted=0)

    complete_chunk = chunk[: last_newline + 1]
    records = split_records(complete_chunk)
    bytes_consumed = len(complete_chunk)
    events_emitted = 0

    for index, (record_start, record_text) in enumerate(records):
        is_last_record = index == len(records) - 1
        status, normalized_events = process_record(
            record_text,
            allow_incomplete=is_last_record,
        )

        if status == "incomplete":
            bytes_consumed = record_start
            break
        if status == "emit":
            append_events(config.output_path, normalized_events)
            events_emitted += len(normalized_events)

    state.offset += bytes_consumed
    save_state(config.state_path, state)

    return ProcessResult(
        bytes_processed=bytes_consumed,
        records_seen=len(records),
        events_emitted=events_emitted,
    )


def run(config: BridgeConfig) -> int:
    while True:
        try:
            result = process_available_records(config)
            if result.events_emitted:
                print(
                    f"emitted {result.events_emitted} Warp events from {config.source_path}",
                    file=sys.stderr,
                )
        except FileNotFoundError:
            print(
                f"Warp network log not found: {config.source_path}",
                file=sys.stderr,
            )
        except Exception as exc:  # pragma: no cover - defensive runtime logging
            print(f"Warp usage bridge error: {exc}", file=sys.stderr)

        if config.once:
            return 0

        time.sleep(config.poll_interval)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv or sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
