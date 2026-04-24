from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import warp_usage_bridge


FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "warp_network_sample.log"
)


class WarpUsageBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.source_path = self.temp_path / "warp_network.log"
        self.output_path = self.temp_path / "warp-usage-events.ndjson"
        self.state_path = self.temp_path / "warp-usage-state.json"
        self.fixture_text = FIXTURE_PATH.read_text(encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def config(self) -> warp_usage_bridge.BridgeConfig:
        return warp_usage_bridge.BridgeConfig(
            source_path=self.source_path,
            output_path=self.output_path,
            state_path=self.state_path,
            poll_interval=0.01,
            once=True,
        )

    def read_events(self) -> list[dict[str, object]]:
        if not self.output_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.output_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_extracts_only_supported_warp_events(self) -> None:
        self.source_path.write_text(self.fixture_text, encoding="utf-8")

        result = warp_usage_bridge.process_available_records(self.config())
        events = self.read_events()

        self.assertEqual(result.events_emitted, 6)
        self.assertEqual(
            [event["event"] for event in events],
            [
                "AgentMode.CreatedAIBlock",
                "AIAutonomy.AutoexecutedRequestedCommand",
                "AgentMode.Code.SuggestedEditReceived",
                "AgentMode.Code.SuggestedEditResolved",
                "Block Creation",
                "AgentMode.CreatedAIBlock",
            ],
        )

    def test_parses_latency_fields_from_created_ai_block(self) -> None:
        self.source_path.write_text(self.fixture_text, encoding="utf-8")

        warp_usage_bridge.process_available_records(self.config())
        created_ai_block = self.read_events()[0]

        self.assertEqual(created_ai_block["time_to_first_token_ms"], 239)
        self.assertEqual(created_ai_block["time_to_last_token_ms"], 1334)
        self.assertEqual(created_ai_block["was_user_facing_error"], False)
        self.assertEqual(created_ai_block["conversation_id"], "conversation-1")

    def test_parses_model_reason_and_terminal_fields(self) -> None:
        self.source_path.write_text(self.fixture_text, encoding="utf-8")

        warp_usage_bridge.process_available_records(self.config())
        events = self.read_events()

        self.assertEqual(events[1]["reason"], "RunToCompletion")
        self.assertEqual(events[2]["model_id"], "claude-4-7-opus-max")
        self.assertEqual(events[4]["terminal_session_id"], 177698983029443)
        self.assertEqual(events[4]["session_id"], 1776988641)

    def test_resumes_from_saved_offset_without_duplicates(self) -> None:
        split_marker = '[2026-04-23 17:55:37,289]: Request'
        first_chunk, second_chunk = self.fixture_text.split(split_marker, 1)
        self.source_path.write_text(first_chunk, encoding="utf-8")

        first_result = warp_usage_bridge.process_available_records(self.config())
        first_events = self.read_events()

        self.assertEqual(first_result.events_emitted, 5)
        self.assertEqual(len(first_events), 5)

        with self.source_path.open("a", encoding="utf-8") as handle:
            handle.write(split_marker)
            handle.write(second_chunk)

        second_result = warp_usage_bridge.process_available_records(self.config())
        all_events = self.read_events()

        self.assertEqual(second_result.events_emitted, 1)
        self.assertEqual(len(all_events), 6)
        self.assertEqual(all_events[-1]["conversation_id"], "conversation-2")
        self.assertEqual(
            [event["client_exchange_id"] for event in all_events if "client_exchange_id" in event],
            ["exchange-1", "exchange-2"],
        )


if __name__ == "__main__":
    unittest.main()
