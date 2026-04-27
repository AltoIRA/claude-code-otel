from __future__ import annotations

import json
import plistlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts import warp_enterprise_snapshot_from_state


class WarpEnterpriseSnapshotFromStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.sqlite_path = self.temp_path / "warp.sqlite"
        self.plist_path = self.temp_path / "dev.warp.Warp-Stable.plist"
        self._create_sqlite_fixture()
        self._create_plist_fixture()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_sqlite_fixture(self) -> None:
        conn = sqlite3.connect(self.sqlite_path)
        try:
            conn.executescript(
                """
                CREATE TABLE workspaces (
                    id INTEGER NOT NULL PRIMARY KEY,
                    name TEXT NOT NULL,
                    server_uid TEXT NOT NULL UNIQUE,
                    is_selected BOOLEAN NOT NULL DEFAULT FALSE
                );
                CREATE TABLE teams (
                    id INTEGER NOT NULL PRIMARY KEY,
                    name TEXT NOT NULL,
                    server_uid TEXT NOT NULL UNIQUE,
                    billing_metadata_json TEXT
                );
                CREATE TABLE workspace_teams (
                    id INTEGER NOT NULL PRIMARY KEY,
                    workspace_server_uid TEXT NOT NULL UNIQUE,
                    team_server_uid TEXT NOT NULL UNIQUE
                );
                CREATE TABLE team_settings (
                    id INTEGER PRIMARY KEY NOT NULL,
                    team_id INTEGER NOT NULL UNIQUE,
                    settings_json TEXT NOT NULL
                );
                CREATE TABLE current_user_information (
                    email TEXT NOT NULL PRIMARY KEY
                );
                CREATE TABLE team_members (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    team_id INTEGER NOT NULL,
                    user_uid TEXT NOT NULL,
                    email TEXT NOT NULL,
                    role TEXT NOT NULL
                );
                CREATE TABLE agent_conversations (
                    id INTEGER PRIMARY KEY NOT NULL,
                    conversation_id TEXT NOT NULL,
                    conversation_data TEXT NOT NULL,
                    last_modified_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE ai_queries (
                    id INTEGER PRIMARY KEY NOT NULL,
                    exchange_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    start_ts DATETIME NOT NULL,
                    input TEXT NOT NULL,
                    working_directory TEXT,
                    output_status TEXT NOT NULL,
                    model_id TEXT NOT NULL DEFAULT '',
                    planning_model_id TEXT NOT NULL DEFAULT '',
                    coding_model_id TEXT NOT NULL DEFAULT ''
                );
                """
            )

            billing_metadata = {
                "customer_type": "Enterprise",
                "tier": {
                    "name": "Alto Solutions",
                    "enterprise_pay_as_you_go_policy": {
                        "enabled": True,
                        "payg_cost_per_thousand_credits_cents": 2500,
                    },
                    "enterprise_credits_auto_reload_policy": {
                        "enabled": True,
                        "auto_reload_cost_cents": 1000,
                        "auto_reload_credit_denomination": 500,
                    },
                },
            }
            settings_json = {
                "usage_based_pricing_settings": {
                    "enabled": True,
                    "max_monthly_spend_cents": 4000,
                },
                "addon_credits_settings": {
                    "auto_reload_enabled": True,
                    "max_monthly_spend_cents": 2000,
                    "selected_auto_reload_credit_denomination": 400,
                },
            }
            conversation_data = {
                "conversation_usage_metadata": {
                    "was_summarized": False,
                    "context_window_usage": 0.75,
                    "credits_spent": 42.5,
                    "token_usage": [
                        {
                            "model_id": "claude-4-7-opus-max",
                            "warp_tokens": 1200,
                            "byok_tokens": 0,
                        },
                        {
                            "model_id": "gpt-5",
                            "warp_tokens": 0,
                            "byok_tokens": 450,
                        },
                    ],
                    "tool_usage_metadata": {
                        "run_command_stats": {
                            "count": 4,
                            "commands_executed": 3,
                        },
                        "apply_file_diff_stats": {
                            "count": 2,
                            "lines_added": 10,
                            "lines_removed": 3,
                            "files_changed": 2,
                        },
                        "read_files_stats": {
                            "count": 5,
                        },
                        "grep_stats": {
                            "count": 1,
                        },
                        "search_codebase_stats": {
                            "count": 2,
                        },
                        "call_mcp_tool_stats": {
                            "count": 1,
                        },
                    },
                }
            }
            ai_query_input = [
                {
                    "Query": {
                        "text": "Ship the Warp enterprise dashboard setup docs",
                    }
                }
            ]

            conn.execute(
                "INSERT INTO workspaces (id, name, server_uid, is_selected) VALUES (?, ?, ?, ?)",
                (1, "Alto", "workspace-1", 1),
            )
            conn.execute(
                "INSERT INTO teams (id, name, server_uid, billing_metadata_json) VALUES (?, ?, ?, ?)",
                (1, "Alto Team", "team-1", json.dumps(billing_metadata)),
            )
            conn.execute(
                "INSERT INTO workspace_teams (id, workspace_server_uid, team_server_uid) VALUES (?, ?, ?)",
                (1, "workspace-1", "team-1"),
            )
            conn.execute(
                "INSERT INTO team_settings (id, team_id, settings_json) VALUES (?, ?, ?)",
                (1, 1, json.dumps(settings_json)),
            )
            conn.execute(
                "INSERT INTO current_user_information (email) VALUES (?)",
                ("eng@example.com",),
            )
            conn.execute(
                "INSERT INTO team_members (team_id, user_uid, email, role) VALUES (?, ?, ?, ?)",
                (1, "user-1", "eng@example.com", "\"Admin\""),
            )
            conn.execute(
                "INSERT INTO agent_conversations (id, conversation_id, conversation_data, last_modified_at) VALUES (?, ?, ?, ?)",
                (
                    1,
                    "conv-1",
                    json.dumps(conversation_data),
                    "2026-04-23 19:55:00",
                ),
            )
            conn.execute(
                """
                INSERT INTO ai_queries (
                    id,
                    exchange_id,
                    conversation_id,
                    start_ts,
                    input,
                    working_directory,
                    output_status,
                    model_id,
                    planning_model_id,
                    coding_model_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "exchange-1",
                    "conv-1",
                    "2026-04-23 19:56:00",
                    json.dumps(ai_query_input),
                    "/tmp/work",
                    "\"Completed\"",
                    "claude-4-7-opus-max",
                    "",
                    "",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _create_plist_fixture(self) -> None:
        plist_payload = {
            "AIRequestLimitInfo": json.dumps(
                {
                    "limit": 1500,
                    "num_requests_used_since_refresh": 321,
                    "next_refresh_time": "2026-05-01T00:00:00Z",
                    "is_unlimited": False,
                    "request_limit_refresh_duration": "Monthly",
                }
            ),
            "AvailableLLMs": json.dumps(
                {
                    "agent_mode": {
                        "choices": [
                            {
                                "id": "claude-4-7-opus-max",
                                "provider": "Anthropic",
                                "usage_metadata": {
                                    "request_multiplier": 1,
                                    "credit_multiplier": 2,
                                },
                            }
                        ]
                    },
                    "coding": {
                        "choices": [
                            {
                                "id": "gpt-5-4-medium",
                                "provider": "OpenAI",
                                "usage_metadata": {
                                    "request_multiplier": 1,
                                    "credit_multiplier": None,
                                },
                            }
                        ]
                    },
                }
            ),
        }

        with self.plist_path.open("wb") as handle:
            plistlib.dump(plist_payload, handle)

    def test_build_snapshot_reads_local_warp_state(self) -> None:
        snapshot = warp_enterprise_snapshot_from_state.build_snapshot(
            sqlite_path=self.sqlite_path,
            preferences_plist_path=self.plist_path,
            max_conversations=25,
        )

        self.assertEqual(snapshot["workspace_uid"], "workspace-1")
        self.assertEqual(snapshot["workspace_name"], "Alto")
        self.assertEqual(snapshot["customer_type"], "enterprise")
        self.assertEqual(snapshot["tier_name"], "Alto Solutions")
        self.assertEqual(snapshot["request_limit"], 1500.0)
        self.assertEqual(snapshot["requests_used_since_last_refresh"], 321.0)
        self.assertEqual(snapshot["current_month_requests_used"], 321.0)
        self.assertEqual(snapshot["next_refresh_time"], "2026-05-01T00:00:00Z")
        self.assertNotIn("current_month_spend_cents", snapshot)
        self.assertNotIn("current_month_credits_purchased", snapshot)
        self.assertTrue(snapshot["usage_based_pricing_enabled"])
        self.assertTrue(snapshot["addon_auto_reload_enabled"])
        self.assertTrue(snapshot["enterprise_payg_enabled"])
        self.assertTrue(snapshot["enterprise_auto_reload_enabled"])

        self.assertEqual(
            snapshot["members"],
            [
                {
                    "email": "eng@example.com",
                    "role": "admin",
                    "is_unlimited": False,
                    "request_limit": 1500.0,
                    "requests_used_since_last_refresh": 321.0,
                }
            ],
        )

        self.assertEqual(
            snapshot["feature_models"][0],
            {
                "feature": "agentMode",
                "model_id": "claude-4-7-opus-max",
                "provider": "Anthropic",
                "credit_multiplier": 2.0,
                "request_multiplier": 1.0,
            },
        )
        self.assertEqual(snapshot["feature_models"][1]["credit_multiplier"], 1.0)

        self.assertEqual(len(snapshot["conversation_usage"]), 1)
        conversation = snapshot["conversation_usage"][0]
        self.assertEqual(conversation["conversation_id"], "conv-1")
        self.assertEqual(
            conversation["title"],
            "Ship the Warp enterprise dashboard setup docs",
        )
        self.assertEqual(conversation["credits_spent"], 42.5)
        self.assertEqual(
            conversation["warp_token_usage"],
            [{"model_id": "claude-4-7-opus-max", "total_tokens": 1200.0}],
        )
        self.assertEqual(
            conversation["byok_token_usage"],
            [{"model_id": "gpt-5", "total_tokens": 450.0}],
        )
        self.assertEqual(conversation["tool_usage"]["run_commands_executed"], 3.0)
        self.assertEqual(conversation["tool_usage"]["files_changed"], 2.0)


if __name__ == "__main__":
    unittest.main()
