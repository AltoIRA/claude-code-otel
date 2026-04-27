#!/usr/bin/env python3
"""Build a normalized Warp Enterprise snapshot from local macOS Warp state."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


LOCAL_TIMEZONE = datetime.now().astimezone().tzinfo or timezone.utc
FEATURE_NAME_MAP = {
    "agent_mode": "agentMode",
    "planning": "planning",
    "coding": "coding",
    "cli_agent": "cliAgent",
    "computer_use": "computerUseAgent",
    "computer_use_agent": "computerUseAgent",
}


def default_sqlite_path() -> Path:
    return (
        Path.home()
        / "Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/dev.warp.Warp-Stable/warp.sqlite"
    )


def default_preferences_plist_path() -> Path:
    return Path.home() / "Library/Preferences/dev.warp.Warp-Stable.plist"


def sqlite_readonly_uri(path: Path) -> str:
    return f"file:{quote(str(path.expanduser()), safe='/')}?mode=ro"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read local Warp state and print a normalized enterprise snapshot JSON document."
    )
    parser.add_argument(
        "--sqlite-path",
        default=os.environ.get("WARP_SQLITE_PATH", str(default_sqlite_path())),
        help="Path to Warp's local SQLite database.",
    )
    parser.add_argument(
        "--preferences-plist-path",
        default=os.environ.get(
            "WARP_PREFERENCES_PLIST_PATH",
            str(default_preferences_plist_path()),
        ),
        help="Path to Warp's local preferences plist.",
    )
    parser.add_argument(
        "--max-conversations",
        type=int,
        default=int(os.environ.get("WARP_CONVERSATION_LIMIT", "25")),
        help="Maximum number of recent conversations to include in the snapshot.",
    )
    return parser.parse_args(argv)


def load_plist(path: Path) -> dict[str, Any]:
    with path.expanduser().open("rb") as handle:
        payload = plistlib.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected a plist dictionary at {path}")
    return payload


def parse_jsonish(value: Any, field_name: str) -> Any:
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a JSON string, object, or array")

    text = value.strip()
    if not text:
        return {}

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} contains invalid JSON") from exc


def require_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return default


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return False


def normalize_iso8601(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return None

    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_sqlite_timestamp(value: Any) -> str:
    normalized = normalize_iso8601(value)
    if normalized is None:
        return datetime.fromtimestamp(0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return normalized


def fetch_selected_workspace(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
          w.server_uid AS workspace_uid,
          w.name AS workspace_name,
          t.id AS team_id,
          t.name AS team_name,
          t.billing_metadata_json AS billing_metadata_json,
          ts.settings_json AS settings_json
        FROM workspaces AS w
        LEFT JOIN workspace_teams AS wt
          ON wt.workspace_server_uid = w.server_uid
        LEFT JOIN teams AS t
          ON t.server_uid = wt.team_server_uid
        LEFT JOIN team_settings AS ts
          ON ts.team_id = t.id
        ORDER BY w.is_selected DESC, w.id ASC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("no Warp workspace was found in local state")
    return dict(row)


def fetch_current_user_email(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT email FROM current_user_information LIMIT 1"
    ).fetchone()
    if row is None or not row["email"]:
        return ""
    return str(row["email"])


def fetch_current_user_role(
    conn: sqlite3.Connection,
    *,
    team_id: int | None,
    email: str,
) -> str:
    if team_id is None or not email:
        return "member"

    row = conn.execute(
        """
        SELECT role
        FROM team_members
        WHERE team_id = ? AND lower(email) = lower(?)
        LIMIT 1
        """,
        (team_id, email),
    ).fetchone()
    if row is None or not row["role"]:
        return "member"
    role = str(row["role"]).strip()
    if role.startswith('"') and role.endswith('"'):
        try:
            parsed_role = json.loads(role)
        except json.JSONDecodeError:
            parsed_role = role
        if isinstance(parsed_role, str):
            role = parsed_role.strip()
    return role.lower() or "member"


def extract_request_limit_info(plist_payload: dict[str, Any]) -> dict[str, Any]:
    request_limit_info = parse_jsonish(
        plist_payload.get("AIRequestLimitInfo"),
        "AIRequestLimitInfo",
    )
    request_limit_info = require_dict(request_limit_info, "AIRequestLimitInfo")
    return request_limit_info


def extract_feature_models(plist_payload: dict[str, Any]) -> list[dict[str, Any]]:
    available_models = parse_jsonish(
        plist_payload.get("AvailableLLMs"),
        "AvailableLLMs",
    )
    available_models = require_dict(available_models, "AvailableLLMs")

    feature_models: list[dict[str, Any]] = []
    for raw_feature, feature_value in available_models.items():
        if raw_feature == "preferred_codex_model_id":
            continue
        if not isinstance(feature_value, dict):
            continue

        choices = feature_value.get("choices")
        if not isinstance(choices, list):
            continue

        feature_name = FEATURE_NAME_MAP.get(raw_feature, raw_feature)
        for choice in choices:
            if not isinstance(choice, dict):
                continue

            model_id = choice.get("id") or choice.get("display_name") or choice.get("base_model_name")
            if not isinstance(model_id, str) or not model_id:
                continue

            usage_metadata = choice.get("usage_metadata")
            if not isinstance(usage_metadata, dict):
                usage_metadata = {}

            request_multiplier = as_float(
                usage_metadata.get("request_multiplier"),
                default=1.0,
            )
            credit_multiplier = as_float(
                usage_metadata.get("credit_multiplier"),
                default=request_multiplier,
            )
            provider = choice.get("provider")
            if not isinstance(provider, str) or not provider:
                provider = "unknown"

            feature_models.append(
                {
                    "feature": feature_name,
                    "model_id": model_id,
                    "provider": provider,
                    "credit_multiplier": credit_multiplier,
                    "request_multiplier": request_multiplier,
                }
            )

    return feature_models


def extract_query_text(input_payload: str) -> str | None:
    try:
        parsed = json.loads(input_payload)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, list):
        return None

    for item in parsed:
        if not isinstance(item, dict):
            continue
        query = item.get("Query")
        if not isinstance(query, dict):
            continue
        text = query.get("text")
        if isinstance(text, str) and text.strip():
            compact = " ".join(text.split())
            return compact[:120]
    return None


def build_conversation_titles(
    conn: sqlite3.Connection,
    conversation_ids: list[str],
) -> dict[str, str]:
    if not conversation_ids:
        return {}

    placeholders = ", ".join("?" for _ in conversation_ids)
    titles: dict[str, str] = {}
    rows = conn.execute(
        f"""
        SELECT conversation_id, input
        FROM ai_queries
        WHERE conversation_id IN ({placeholders})
        ORDER BY start_ts DESC
        """,
        conversation_ids,
    ).fetchall()
    for row in rows:
        conversation_id = str(row["conversation_id"])
        if conversation_id in titles:
            continue
        title = extract_query_text(str(row["input"]))
        if title:
            titles[conversation_id] = title
    return titles


def build_conversation_usage(
    conn: sqlite3.Connection,
    *,
    max_conversations: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT conversation_id, conversation_data, last_modified_at
        FROM agent_conversations
        ORDER BY last_modified_at DESC
        LIMIT ?
        """,
        (max_conversations,),
    ).fetchall()
    conversation_ids = [str(row["conversation_id"]) for row in rows]
    titles = build_conversation_titles(conn, conversation_ids)

    conversations: list[dict[str, Any]] = []
    for row in rows:
        conversation_id = str(row["conversation_id"])
        conversation_data = parse_jsonish(
            row["conversation_data"],
            f"agent_conversations[{conversation_id}].conversation_data",
        )
        conversation_data = require_dict(
            conversation_data,
            f"agent_conversations[{conversation_id}].conversation_data",
        )

        usage_metadata = conversation_data.get("conversation_usage_metadata")
        if not isinstance(usage_metadata, dict):
            usage_metadata = {}

        token_usage = usage_metadata.get("token_usage")
        if not isinstance(token_usage, list):
            token_usage = []

        warp_token_usage: list[dict[str, Any]] = []
        byok_token_usage: list[dict[str, Any]] = []
        for token_entry in token_usage:
            if not isinstance(token_entry, dict):
                continue
            model_id = token_entry.get("model_id")
            if not isinstance(model_id, str) or not model_id:
                continue

            warp_tokens = as_float(token_entry.get("warp_tokens"))
            byok_tokens = as_float(token_entry.get("byok_tokens"))
            if warp_tokens > 0:
                warp_token_usage.append(
                    {
                        "model_id": model_id,
                        "total_tokens": warp_tokens,
                    }
                )
            if byok_tokens > 0:
                byok_token_usage.append(
                    {
                        "model_id": model_id,
                        "total_tokens": byok_tokens,
                    }
                )

        tool_usage_metadata = usage_metadata.get("tool_usage_metadata")
        if not isinstance(tool_usage_metadata, dict):
            tool_usage_metadata = {}

        def nested_count(*keys: str) -> float:
            current: Any = tool_usage_metadata
            for key in keys:
                if not isinstance(current, dict):
                    return 0.0
                current = current.get(key)
            return as_float(current)

        conversations.append(
            {
                "conversation_id": conversation_id,
                "last_updated": normalize_sqlite_timestamp(row["last_modified_at"]),
                "title": titles.get(conversation_id, conversation_id),
                "credits_spent": as_float(usage_metadata.get("credits_spent")),
                "context_window_usage": as_float(usage_metadata.get("context_window_usage")),
                "summarized": as_bool(usage_metadata.get("was_summarized")),
                "warp_token_usage": warp_token_usage,
                "byok_token_usage": byok_token_usage,
                "tool_usage": {
                    "run_commands_executed": nested_count("run_command_stats", "commands_executed"),
                    "apply_file_diff_count": nested_count("apply_file_diff_stats", "count"),
                    "lines_added": nested_count("apply_file_diff_stats", "lines_added"),
                    "lines_removed": nested_count("apply_file_diff_stats", "lines_removed"),
                    "files_changed": nested_count("apply_file_diff_stats", "files_changed"),
                    "read_files_count": nested_count("read_files_stats", "count"),
                    "grep_count": nested_count("grep_stats", "count"),
                    "search_codebase_count": nested_count("search_codebase_stats", "count"),
                    "call_mcp_tool_count": nested_count("call_mcp_tool_stats", "count"),
                },
            }
        )

    return conversations


def build_snapshot(
    *,
    sqlite_path: Path,
    preferences_plist_path: Path,
    max_conversations: int,
) -> dict[str, Any]:
    plist_payload = load_plist(preferences_plist_path)
    request_limit_info = extract_request_limit_info(plist_payload)
    feature_models = extract_feature_models(plist_payload)

    conn = sqlite3.connect(sqlite_readonly_uri(sqlite_path), uri=True)
    conn.row_factory = sqlite3.Row
    try:
        workspace = fetch_selected_workspace(conn)
        current_user_email = fetch_current_user_email(conn)
        current_user_role = fetch_current_user_role(
            conn,
            team_id=workspace.get("team_id"),
            email=current_user_email,
        )
        conversation_usage = build_conversation_usage(
            conn,
            max_conversations=max_conversations,
        )
    finally:
        conn.close()

    billing_metadata = parse_jsonish(
        workspace.get("billing_metadata_json"),
        "billing_metadata_json",
    )
    if not isinstance(billing_metadata, dict):
        billing_metadata = {}

    settings = parse_jsonish(
        workspace.get("settings_json"),
        "settings_json",
    )
    if not isinstance(settings, dict):
        settings = {}

    tier = billing_metadata.get("tier")
    if not isinstance(tier, dict):
        tier = {}
    tier_name = tier.get("name")
    if not isinstance(tier_name, str) or not tier_name:
        tier_name = str(workspace["workspace_name"])

    usage_based_pricing_settings = settings.get("usage_based_pricing_settings")
    if not isinstance(usage_based_pricing_settings, dict):
        usage_based_pricing_settings = {}

    addon_credits_settings = settings.get("addon_credits_settings")
    if not isinstance(addon_credits_settings, dict):
        addon_credits_settings = {}

    enterprise_payg_policy = tier.get("enterprise_pay_as_you_go_policy")
    if not isinstance(enterprise_payg_policy, dict):
        enterprise_payg_policy = {}

    enterprise_auto_reload_policy = tier.get("enterprise_credits_auto_reload_policy")
    if not isinstance(enterprise_auto_reload_policy, dict):
        enterprise_auto_reload_policy = {}

    customer_type = billing_metadata.get("customer_type")
    if not isinstance(customer_type, str) or not customer_type:
        customer_type = "enterprise"

    request_limit = as_float(request_limit_info.get("limit"))
    requests_used_since_last_refresh = as_float(
        request_limit_info.get("num_requests_used_since_refresh")
    )
    next_refresh_time = normalize_iso8601(request_limit_info.get("next_refresh_time"))
    request_limit_refresh_duration = request_limit_info.get("request_limit_refresh_duration")
    if request_limit_refresh_duration == "Monthly":
        current_month_requests_used = requests_used_since_last_refresh
    else:
        current_month_requests_used = 0.0

    members: list[dict[str, Any]] = []
    if current_user_email:
        members.append(
            {
                "email": current_user_email,
                "role": current_user_role,
                "is_unlimited": as_bool(request_limit_info.get("is_unlimited")),
                "request_limit": request_limit,
                "requests_used_since_last_refresh": requests_used_since_last_refresh,
            }
        )

    snapshot = {
        "workspace_uid": str(workspace["workspace_uid"]),
        "workspace_name": str(workspace["workspace_name"]),
        "customer_type": customer_type.lower(),
        "tier_name": tier_name,
        "current_period_end": next_refresh_time,
        "request_limit": request_limit,
        "requests_used_since_last_refresh": requests_used_since_last_refresh,
        "next_refresh_time": next_refresh_time,
        "current_month_requests_used": current_month_requests_used,
        "usage_based_pricing_enabled": as_bool(usage_based_pricing_settings.get("enabled")),
        "usage_based_pricing_max_monthly_spend_cents": as_float(
            usage_based_pricing_settings.get("max_monthly_spend_cents")
        ),
        "addon_auto_reload_enabled": as_bool(addon_credits_settings.get("auto_reload_enabled")),
        "addon_max_monthly_spend_cents": as_float(
            addon_credits_settings.get("max_monthly_spend_cents")
        ),
        "addon_selected_auto_reload_credit_denomination": as_float(
            addon_credits_settings.get("selected_auto_reload_credit_denomination")
        ),
        "enterprise_payg_enabled": as_bool(enterprise_payg_policy.get("enabled")),
        "enterprise_payg_cost_per_thousand_credits_cents": as_float(
            enterprise_payg_policy.get("payg_cost_per_thousand_credits_cents")
        ),
        "enterprise_auto_reload_enabled": as_bool(
            enterprise_auto_reload_policy.get("enabled")
        ),
        "enterprise_auto_reload_cost_cents": as_float(
            enterprise_auto_reload_policy.get("auto_reload_cost_cents")
        ),
        "enterprise_auto_reload_credit_denomination": as_float(
            enterprise_auto_reload_policy.get("auto_reload_credit_denomination")
        ),
        "bonus_grants_remaining": 0.0,
        "bonus_grants_total": 0.0,
        "members": members,
        "feature_models": feature_models,
        "conversation_usage": conversation_usage,
    }
    return snapshot


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    snapshot = build_snapshot(
        sqlite_path=Path(args.sqlite_path),
        preferences_plist_path=Path(args.preferences_plist_path),
        max_conversations=args.max_conversations,
    )
    print(json.dumps(snapshot, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
