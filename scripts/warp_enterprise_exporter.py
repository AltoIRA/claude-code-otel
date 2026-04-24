#!/usr/bin/env python3
"""Expose normalized Warp Enterprise local-state snapshots as Prometheus metrics."""

from __future__ import annotations

import argparse
import concurrent.futures
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    from scripts import warp_enterprise_snapshot_from_state
except ModuleNotFoundError:
    import warp_enterprise_snapshot_from_state


MODEL_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
DEFAULT_ESTIMATED_CENTS_PER_CREDIT = 1.5


@dataclass(frozen=True)
class MetricSample:
    name: str
    value: float
    labels: dict[str, str]


def optional_float_env(name: str, default: float | None = None) -> float | None:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    return float(value)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve Prometheus metrics for Warp Enterprise local-state snapshots."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("WARP_EXPORTER_PORT", "9498")),
        help="Port to bind the exporter HTTP server to.",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("WARP_EXPORTER_HOST", "127.0.0.1"),
        help="Host interface to bind the exporter HTTP server to.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("WARP_ENTERPRISE_SNAPSHOT_TIMEOUT", "10")),
        help="Timeout in seconds for building the local Warp snapshot.",
    )
    parser.add_argument(
        "--sqlite-path",
        default=os.environ.get(
            "WARP_SQLITE_PATH",
            str(warp_enterprise_snapshot_from_state.default_sqlite_path()),
        ),
        help="Path to Warp's local SQLite database.",
    )
    parser.add_argument(
        "--preferences-plist-path",
        default=os.environ.get(
            "WARP_PREFERENCES_PLIST_PATH",
            str(warp_enterprise_snapshot_from_state.default_preferences_plist_path()),
        ),
        help="Path to Warp's local preferences plist.",
    )
    parser.add_argument(
        "--max-conversations",
        type=int,
        default=int(os.environ.get("WARP_CONVERSATION_LIMIT", "25")),
        help="Maximum number of recent conversations to include in the snapshot.",
    )
    parser.add_argument(
        "--estimated-cents-per-credit",
        type=float,
        default=optional_float_env(
            "WARP_ESTIMATED_CENTS_PER_CREDIT",
            DEFAULT_ESTIMATED_CENTS_PER_CREDIT,
        ),
        help=(
            "Manual cents-per-credit rate used to estimate Warp spend from local "
            f"conversation credits. Defaults to {DEFAULT_ESTIMATED_CENTS_PER_CREDIT:g} "
            "until the actual Enterprise rate is known."
        ),
    )
    return parser.parse_args(argv)


def require_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    return value


def require_scalar(snapshot: dict[str, Any], field_name: str, allowed_types: tuple[type[Any], ...]) -> Any:
    value = snapshot.get(field_name)
    if not isinstance(value, allowed_types):
        type_names = ", ".join(t.__name__ for t in allowed_types)
        raise ValueError(f"{field_name} must be one of: {type_names}")
    return value


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    require_scalar(snapshot, "workspace_uid", (str,))
    require_scalar(snapshot, "workspace_name", (str,))
    require_scalar(snapshot, "customer_type", (str,))
    require_scalar(snapshot, "tier_name", (str,))
    current_period_end = snapshot.get("current_period_end")
    next_refresh_time = snapshot.get("next_refresh_time")
    if current_period_end is not None and not isinstance(current_period_end, str):
        raise ValueError("current_period_end must be a string or null")
    if next_refresh_time is not None and not isinstance(next_refresh_time, str):
        raise ValueError("next_refresh_time must be a string or null")
    require_scalar(snapshot, "request_limit", (int, float))
    require_scalar(snapshot, "requests_used_since_last_refresh", (int, float))
    require_scalar(snapshot, "current_month_requests_used", (int, float))
    require_scalar(snapshot, "usage_based_pricing_enabled", (bool,))
    require_scalar(snapshot, "usage_based_pricing_max_monthly_spend_cents", (int, float))
    require_scalar(snapshot, "addon_auto_reload_enabled", (bool,))
    require_scalar(snapshot, "addon_max_monthly_spend_cents", (int, float))
    require_scalar(snapshot, "addon_selected_auto_reload_credit_denomination", (int, float))
    require_scalar(snapshot, "enterprise_payg_enabled", (bool,))
    require_scalar(snapshot, "enterprise_payg_cost_per_thousand_credits_cents", (int, float))
    require_scalar(snapshot, "enterprise_auto_reload_enabled", (bool,))
    require_scalar(snapshot, "enterprise_auto_reload_cost_cents", (int, float))
    require_scalar(snapshot, "enterprise_auto_reload_credit_denomination", (int, float))
    require_scalar(snapshot, "bonus_grants_remaining", (int, float))
    require_scalar(snapshot, "bonus_grants_total", (int, float))

    members = require_list(snapshot.get("members"), "members")
    for index, member in enumerate(members):
        member_obj = require_dict(member, f"members[{index}]")
        require_scalar(member_obj, "email", (str,))
        require_scalar(member_obj, "role", (str,))
        require_scalar(member_obj, "is_unlimited", (bool,))
        require_scalar(member_obj, "request_limit", (int, float))
        require_scalar(member_obj, "requests_used_since_last_refresh", (int, float))

    feature_models = require_list(snapshot.get("feature_models"), "feature_models")
    for index, feature_model in enumerate(feature_models):
        feature_model_obj = require_dict(feature_model, f"feature_models[{index}]")
        require_scalar(feature_model_obj, "feature", (str,))
        require_scalar(feature_model_obj, "model_id", (str,))
        require_scalar(feature_model_obj, "provider", (str,))
        require_scalar(feature_model_obj, "credit_multiplier", (int, float))
        require_scalar(feature_model_obj, "request_multiplier", (int, float))

    conversation_usage = require_list(snapshot.get("conversation_usage"), "conversation_usage")
    for index, conversation in enumerate(conversation_usage):
        conversation_obj = require_dict(conversation, f"conversation_usage[{index}]")
        require_scalar(conversation_obj, "conversation_id", (str,))
        require_scalar(conversation_obj, "last_updated", (str,))
        require_scalar(conversation_obj, "title", (str,))
        require_scalar(conversation_obj, "credits_spent", (int, float))
        require_scalar(conversation_obj, "context_window_usage", (int, float))
        require_scalar(conversation_obj, "summarized", (bool,))

        for token_key in ("warp_token_usage", "byok_token_usage"):
            token_entries = require_list(conversation_obj.get(token_key), f"conversation_usage[{index}].{token_key}")
            for token_index, token_entry in enumerate(token_entries):
                token_obj = require_dict(token_entry, f"{token_key}[{token_index}]")
                require_scalar(token_obj, "model_id", (str,))
                require_scalar(token_obj, "total_tokens", (int, float))

        tool_usage = require_dict(conversation_obj.get("tool_usage"), f"conversation_usage[{index}].tool_usage")
        for field_name in (
            "run_commands_executed",
            "apply_file_diff_count",
            "lines_added",
            "lines_removed",
            "files_changed",
            "read_files_count",
            "grep_count",
            "search_codebase_count",
            "call_mcp_tool_count",
        ):
            require_scalar(tool_usage, field_name, (int, float))


def bool_to_float(value: bool) -> float:
    return 1.0 if value else 0.0


def sanitize_label_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def finite_or_nan(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return value
    return float(value)


def parse_optional_timestamp(value: Any) -> float:
    if value in (None, ""):
        return float("nan")
    if not isinstance(value, str):
        raise ValueError("timestamp values must be strings or null")

    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(timezone.utc).timestamp()


def normalize_model_key(model_id: str) -> str:
    tokens = MODEL_TOKEN_PATTERN.findall(model_id.lower())
    return " ".join(sorted(tokens))


def build_credit_multiplier_map(feature_models: list[dict[str, Any]]) -> dict[str, float]:
    multipliers: dict[str, float] = {}
    for feature_model in feature_models:
        model_key = normalize_model_key(str(feature_model["model_id"]))
        if not model_key:
            continue
        credit_multiplier = float(feature_model["credit_multiplier"])
        if credit_multiplier <= 0:
            credit_multiplier = 1.0
        existing = multipliers.get(model_key, 0.0)
        multipliers[model_key] = max(existing, credit_multiplier)
    return multipliers


def build_metric_samples(
    snapshot: dict[str, Any],
    *,
    estimated_cents_per_credit: float | None = None,
) -> list[MetricSample]:
    workspace_labels = {
        "workspace_uid": sanitize_label_value(snapshot["workspace_uid"]),
        "workspace_name": sanitize_label_value(snapshot["workspace_name"]),
        "customer_type": sanitize_label_value(snapshot["customer_type"]),
        "tier_name": sanitize_label_value(snapshot["tier_name"]),
    }

    request_limit = float(snapshot["request_limit"])
    requests_used = float(snapshot["requests_used_since_last_refresh"])
    if request_limit > 0:
        allocation_remaining = request_limit - requests_used
    else:
        allocation_remaining = float("nan")

    samples = [
        MetricSample(
            "warp_workspace_requests_used_since_last_refresh",
            requests_used,
            workspace_labels,
        ),
        MetricSample("warp_workspace_request_limit", request_limit, workspace_labels),
        MetricSample(
            "warp_workspace_current_period_end_timestamp_seconds",
            parse_optional_timestamp(snapshot.get("current_period_end")),
            workspace_labels,
        ),
        MetricSample(
            "warp_workspace_next_refresh_timestamp_seconds",
            parse_optional_timestamp(snapshot.get("next_refresh_time")),
            workspace_labels,
        ),
        MetricSample(
            "warp_workspace_request_allocation_remaining",
            finite_or_nan(allocation_remaining),
            workspace_labels,
        ),
        MetricSample(
            "warp_workspace_bonus_grants_remaining",
            float(snapshot["bonus_grants_remaining"]),
            workspace_labels,
        ),
        MetricSample(
            "warp_workspace_bonus_grants_total",
            float(snapshot["bonus_grants_total"]),
            workspace_labels,
        ),
        MetricSample(
            "warp_workspace_current_month_requests_used",
            float(snapshot["current_month_requests_used"]),
            workspace_labels,
        ),
        MetricSample(
            "warp_workspace_usage_based_pricing_enabled",
            bool_to_float(bool(snapshot["usage_based_pricing_enabled"])),
            workspace_labels,
        ),
        MetricSample(
            "warp_workspace_usage_based_pricing_max_monthly_spend_cents",
            float(snapshot["usage_based_pricing_max_monthly_spend_cents"]),
            workspace_labels,
        ),
        MetricSample(
            "warp_workspace_addon_auto_reload_enabled",
            bool_to_float(bool(snapshot["addon_auto_reload_enabled"])),
            workspace_labels,
        ),
        MetricSample(
            "warp_workspace_addon_max_monthly_spend_cents",
            float(snapshot["addon_max_monthly_spend_cents"]),
            workspace_labels,
        ),
        MetricSample(
            "warp_workspace_addon_selected_auto_reload_credit_denomination",
            float(snapshot["addon_selected_auto_reload_credit_denomination"]),
            workspace_labels,
        ),
        MetricSample(
            "warp_workspace_enterprise_payg_enabled",
            bool_to_float(bool(snapshot["enterprise_payg_enabled"])),
            workspace_labels,
        ),
        MetricSample(
            "warp_workspace_enterprise_payg_cost_per_thousand_credits_cents",
            float(snapshot["enterprise_payg_cost_per_thousand_credits_cents"]),
            workspace_labels,
        ),
        MetricSample(
            "warp_workspace_enterprise_auto_reload_enabled",
            bool_to_float(bool(snapshot["enterprise_auto_reload_enabled"])),
            workspace_labels,
        ),
        MetricSample(
            "warp_workspace_enterprise_auto_reload_cost_cents",
            float(snapshot["enterprise_auto_reload_cost_cents"]),
            workspace_labels,
        ),
        MetricSample(
            "warp_workspace_enterprise_auto_reload_credit_denomination",
            float(snapshot["enterprise_auto_reload_credit_denomination"]),
            workspace_labels,
        ),
    ]

    if estimated_cents_per_credit is not None:
        samples.append(
            MetricSample(
                "warp_estimated_cents_per_credit",
                float(estimated_cents_per_credit),
                workspace_labels,
            )
        )

    for member in snapshot["members"]:
        member_labels = {
            **workspace_labels,
            "email": sanitize_label_value(member["email"]),
            "role": sanitize_label_value(member["role"]),
            "is_unlimited": sanitize_label_value(str(member["is_unlimited"]).lower()),
        }
        samples.append(
            MetricSample(
                "warp_member_requests_used_since_last_refresh",
                float(member["requests_used_since_last_refresh"]),
                member_labels,
            )
        )
        samples.append(
            MetricSample(
                "warp_member_request_limit",
                float(member["request_limit"]),
                member_labels,
            )
        )

    multiplier_lookup = build_credit_multiplier_map(snapshot["feature_models"])
    for feature_model in snapshot["feature_models"]:
        feature_model_labels = {
            **workspace_labels,
            "feature": sanitize_label_value(feature_model["feature"]),
            "model_id": sanitize_label_value(feature_model["model_id"]),
            "provider": sanitize_label_value(feature_model["provider"]),
        }
        samples.append(
            MetricSample(
                "warp_model_credit_multiplier",
                float(feature_model["credit_multiplier"]),
                feature_model_labels,
            )
        )
        samples.append(
            MetricSample(
                "warp_model_request_multiplier",
                float(feature_model["request_multiplier"]),
                feature_model_labels,
            )
        )

    for conversation in snapshot["conversation_usage"]:
        conversation_labels = {
            **workspace_labels,
            "conversation_id": sanitize_label_value(conversation["conversation_id"]),
            "title": sanitize_label_value(conversation["title"]),
            "last_updated": sanitize_label_value(conversation["last_updated"]),
            "summarized": sanitize_label_value(str(conversation["summarized"]).lower()),
        }
        samples.append(
            MetricSample(
                "warp_conversation_last_updated_timestamp_seconds",
                parse_optional_timestamp(conversation["last_updated"]),
                conversation_labels,
            )
        )
        samples.append(
            MetricSample(
                "warp_conversation_credits_spent_total",
                float(conversation["credits_spent"]),
                conversation_labels,
            )
        )

        weighted_warp_tokens: list[tuple[str, float, float]] = []
        for token_source in ("warp_token_usage", "byok_token_usage"):
            usage_type = "warp" if token_source == "warp_token_usage" else "byok"
            for token_entry in conversation[token_source]:
                token_labels = {
                    **conversation_labels,
                    "token_source": usage_type,
                    "model_id": sanitize_label_value(token_entry["model_id"]),
                }
                token_total = float(token_entry["total_tokens"])
                samples.append(
                    MetricSample(
                        "warp_conversation_tokens_total",
                        token_total,
                        token_labels,
                    )
                )

                if usage_type == "warp" and estimated_cents_per_credit is not None and token_total > 0:
                    model_key = normalize_model_key(str(token_entry["model_id"]))
                    multiplier = multiplier_lookup.get(model_key, 1.0)
                    weighted_warp_tokens.append((str(token_entry["model_id"]), token_total, token_total * multiplier))

        if estimated_cents_per_credit is not None and float(conversation["credits_spent"]) > 0:
            total_weight = sum(weight for _, _, weight in weighted_warp_tokens if weight > 0)
            if total_weight > 0:
                total_estimated_spend_cents = float(conversation["credits_spent"]) * float(estimated_cents_per_credit)
                for model_id, _, weight in weighted_warp_tokens:
                    if weight <= 0:
                        continue
                    samples.append(
                        MetricSample(
                            "warp_conversation_model_estimated_spend_cents_total",
                            total_estimated_spend_cents * (weight / total_weight),
                            {
                                **workspace_labels,
                                "conversation_id": sanitize_label_value(conversation["conversation_id"]),
                                "title": sanitize_label_value(conversation["title"]),
                                "model_id": sanitize_label_value(model_id),
                            },
                        )
                    )

        tool_usage = conversation["tool_usage"]
        tool_metric_mapping = {
            "run_commands_executed": "run_commands_executed",
            "apply_file_diff_count": "apply_file_diff_count",
            "lines_added": "lines_added",
            "lines_removed": "lines_removed",
            "files_changed": "files_changed",
            "read_files_count": "read_files_count",
            "grep_count": "grep_count",
            "search_codebase_count": "search_codebase_count",
            "call_mcp_tool_count": "call_mcp_tool_count",
        }
        for tool_name in tool_metric_mapping:
            samples.append(
                MetricSample(
                    "warp_conversation_tool_calls_total",
                    float(tool_usage[tool_name]),
                    {
                        **conversation_labels,
                        "tool": tool_name,
                    },
                )
            )

    return samples


def escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def format_metric_sample(sample: MetricSample) -> str:
    if sample.labels:
        label_text = ",".join(
            f'{key}="{escape_label_value(value)}"'
            for key, value in sorted(sample.labels.items())
        )
        return f"{sample.name}{{{label_text}}} {format_float(sample.value)}"
    return f"{sample.name} {format_float(sample.value)}"


def format_float(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    return repr(float(value))


def render_metrics(
    samples: list[MetricSample],
    *,
    scrape_success: bool,
    snapshot_timestamp: float,
) -> str:
    lines = [format_metric_sample(sample) for sample in samples]
    lines.append(
        format_metric_sample(
            MetricSample("warp_exporter_scrape_success", bool_to_float(scrape_success), {})
        )
    )
    lines.append(
        format_metric_sample(
            MetricSample(
                "warp_exporter_snapshot_timestamp_seconds",
                snapshot_timestamp,
                {},
            )
        )
    )
    return "\n".join(lines) + "\n"


class SnapshotCache:
    def __init__(
        self,
        *,
        sqlite_path: str,
        preferences_plist_path: str,
        max_conversations: int,
        timeout: float,
        estimated_cents_per_credit: float | None,
    ) -> None:
        self.sqlite_path = Path(sqlite_path)
        self.preferences_plist_path = Path(preferences_plist_path)
        self.max_conversations = max_conversations
        self.timeout = timeout
        self.estimated_cents_per_credit = estimated_cents_per_credit
        self.last_success_samples: list[MetricSample] = []
        self.last_success_timestamp = float("nan")

    def load_snapshot(self) -> dict[str, Any]:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            warp_enterprise_snapshot_from_state.build_snapshot,
            sqlite_path=self.sqlite_path,
            preferences_plist_path=self.preferences_plist_path,
            max_conversations=self.max_conversations,
        )
        try:
            return future.result(timeout=self.timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise RuntimeError(f"snapshot refresh timed out after {self.timeout:g}s") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def refresh(self) -> tuple[bool, str | None]:
        try:
            snapshot = self.load_snapshot()
            validate_snapshot(snapshot)
            self.last_success_samples = build_metric_samples(
                snapshot,
                estimated_cents_per_credit=self.estimated_cents_per_credit,
            )
            self.last_success_timestamp = time.time()
            return (True, None)
        except Exception as exc:
            return (False, str(exc))

    def render(self) -> tuple[str, bool, str | None]:
        scrape_success, error_message = self.refresh()
        metrics_text = render_metrics(
            self.last_success_samples,
            scrape_success=scrape_success,
            snapshot_timestamp=self.last_success_timestamp,
        )
        return (metrics_text, scrape_success, error_message)


def make_handler(cache: SnapshotCache) -> type[BaseHTTPRequestHandler]:
    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path not in ("/", "/metrics"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            body, scrape_success, error_message = cache.render()
            status = HTTPStatus.OK if scrape_success or cache.last_success_samples else HTTPStatus.SERVICE_UNAVAILABLE
            encoded = body.encode("utf-8")

            self.send_response(status)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

            if error_message:
                print(f"Warp exporter scrape failed: {error_message}", file=sys.stderr)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return MetricsHandler


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    cache = SnapshotCache(
        sqlite_path=args.sqlite_path,
        preferences_plist_path=args.preferences_plist_path,
        max_conversations=args.max_conversations,
        timeout=args.timeout,
        estimated_cents_per_credit=args.estimated_cents_per_credit,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(cache))

    print(
        f"Warp Enterprise exporter listening on http://{args.host}:{args.port}/metrics",
        file=sys.stderr,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
