from __future__ import annotations

import json
import math
import unittest
from unittest import mock

from scripts import warp_enterprise_exporter


VALID_SNAPSHOT = {
    "workspace_uid": "workspace-1",
    "workspace_name": "Altoira Platform",
    "customer_type": "enterprise",
    "tier_name": "Enterprise",
    "current_period_end": "2026-04-30T00:00:00Z",
    "request_limit": 1500,
    "requests_used_since_last_refresh": 450,
    "next_refresh_time": "2026-05-01T00:00:00Z",
    "current_month_requests_used": 700,
    "usage_based_pricing_enabled": True,
    "usage_based_pricing_max_monthly_spend_cents": 5000,
    "addon_auto_reload_enabled": True,
    "addon_max_monthly_spend_cents": 6000,
    "addon_selected_auto_reload_credit_denomination": 400,
    "enterprise_payg_enabled": True,
    "enterprise_payg_cost_per_thousand_credits_cents": 2500,
    "enterprise_auto_reload_enabled": True,
    "enterprise_auto_reload_cost_cents": 1000,
    "enterprise_auto_reload_credit_denomination": 500,
    "bonus_grants_remaining": 120,
    "bonus_grants_total": 240,
    "members": [
        {
            "email": "eng1@example.com",
            "role": "admin",
            "is_unlimited": False,
            "request_limit": 1000,
            "requests_used_since_last_refresh": 300,
        }
    ],
    "feature_models": [
        {
            "feature": "agentMode",
            "model_id": "claude-4-7-opus-max",
            "provider": "anthropic",
            "credit_multiplier": 2.0,
            "request_multiplier": 1.0,
        },
        {
            "feature": "agentMode",
            "model_id": "gpt-5.4-medium",
            "provider": "openai",
            "credit_multiplier": 1.0,
            "request_multiplier": 1.0,
        },
    ],
    "conversation_usage": [
        {
            "conversation_id": "conv-1",
            "last_updated": "2026-04-23T00:00:00Z",
            "title": "Fix auth flow",
            "credits_spent": 42,
            "context_window_usage": 1024,
            "summarized": False,
            "warp_token_usage": [
                {"model_id": "Claude Opus 4.7 (max)", "total_tokens": 1200},
                {"model_id": "GPT-5.4 Medium", "total_tokens": 800},
            ],
            "byok_token_usage": [
                {"model_id": "gpt-5", "total_tokens": 100000}
            ],
            "tool_usage": {
                "run_commands_executed": 7,
                "apply_file_diff_count": 3,
                "lines_added": 25,
                "lines_removed": 8,
                "files_changed": 4,
                "read_files_count": 11,
                "grep_count": 5,
                "search_codebase_count": 2,
                "call_mcp_tool_count": 1,
            },
        }
    ],
}


class WarpEnterpriseExporterTests(unittest.TestCase):
    def test_parse_args_defaults_to_local_state_inputs_and_guess_rate(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            args = warp_enterprise_exporter.parse_args([])

        self.assertTrue(args.sqlite_path.endswith("warp.sqlite"))
        self.assertTrue(args.preferences_plist_path.endswith("dev.warp.Warp-Stable.plist"))
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.max_conversations, 25)
        self.assertEqual(args.estimated_cents_per_credit, 1.5)

    def test_validate_snapshot_accepts_expected_contract(self) -> None:
        warp_enterprise_exporter.validate_snapshot(VALID_SNAPSHOT)

    def test_builds_expected_metrics_without_estimated_spend(self) -> None:
        samples = warp_enterprise_exporter.build_metric_samples(VALID_SNAPSHOT)
        rendered = warp_enterprise_exporter.render_metrics(
            samples,
            scrape_success=True,
            snapshot_timestamp=1713916800.0,
        )

        self.assertIn(
            'warp_workspace_request_allocation_remaining{customer_type="enterprise",tier_name="Enterprise",workspace_name="Altoira Platform",workspace_uid="workspace-1"} 1050.0',
            rendered,
        )
        self.assertIn(
            'warp_member_requests_used_since_last_refresh{customer_type="enterprise",email="eng1@example.com",is_unlimited="false",role="admin",tier_name="Enterprise",workspace_name="Altoira Platform",workspace_uid="workspace-1"} 300.0',
            rendered,
        )
        self.assertIn(
            'warp_model_credit_multiplier{customer_type="enterprise",feature="agentMode",model_id="claude-4-7-opus-max",provider="anthropic",tier_name="Enterprise",workspace_name="Altoira Platform",workspace_uid="workspace-1"} 2.0',
            rendered,
        )
        self.assertIn(
            'warp_conversation_tokens_total{conversation_id="conv-1",customer_type="enterprise",last_updated="2026-04-23T00:00:00Z",model_id="Claude Opus 4.7 (max)",summarized="false",tier_name="Enterprise",title="Fix auth flow",token_source="warp",workspace_name="Altoira Platform",workspace_uid="workspace-1"} 1200.0',
            rendered,
        )
        self.assertIn(
            'warp_conversation_last_updated_timestamp_seconds{conversation_id="conv-1",customer_type="enterprise",last_updated="2026-04-23T00:00:00Z",summarized="false",tier_name="Enterprise",title="Fix auth flow",workspace_name="Altoira Platform",workspace_uid="workspace-1"} 1776902400.0',
            rendered,
        )
        self.assertIn("warp_exporter_scrape_success 1.0", rendered)
        self.assertIn("warp_exporter_snapshot_timestamp_seconds 1713916800.0", rendered)
        self.assertNotIn("warp_workspace_current_month_spend_cents", rendered)
        self.assertNotIn("warp_workspace_current_month_credits_purchased", rendered)
        self.assertNotIn("warp_conversation_model_estimated_spend_cents_total", rendered)

    def test_builds_weighted_estimated_spend_and_excludes_byok_tokens(self) -> None:
        samples = warp_enterprise_exporter.build_metric_samples(
            VALID_SNAPSHOT,
            estimated_cents_per_credit=10.0,
        )
        rendered = warp_enterprise_exporter.render_metrics(
            samples,
            scrape_success=True,
            snapshot_timestamp=1713916800.0,
        )

        self.assertIn(
            'warp_estimated_cents_per_credit{customer_type="enterprise",tier_name="Enterprise",workspace_name="Altoira Platform",workspace_uid="workspace-1"} 10.0',
            rendered,
        )
        self.assertIn(
            'warp_conversation_model_estimated_spend_cents_total{conversation_id="conv-1",customer_type="enterprise",model_id="Claude Opus 4.7 (max)",tier_name="Enterprise",title="Fix auth flow",workspace_name="Altoira Platform",workspace_uid="workspace-1"} 315.0',
            rendered,
        )
        self.assertIn(
            'warp_conversation_model_estimated_spend_cents_total{conversation_id="conv-1",customer_type="enterprise",model_id="GPT-5.4 Medium",tier_name="Enterprise",title="Fix auth flow",workspace_name="Altoira Platform",workspace_uid="workspace-1"} 105.0',
            rendered,
        )
        self.assertNotIn(
            'warp_conversation_model_estimated_spend_cents_total{conversation_id="conv-1",customer_type="enterprise",model_id="gpt-5"',
            rendered,
        )

    def test_request_allocation_can_render_nan_for_unlimited_workspace(self) -> None:
        unlimited_snapshot = json.loads(json.dumps(VALID_SNAPSHOT))
        unlimited_snapshot["request_limit"] = 0

        samples = warp_enterprise_exporter.build_metric_samples(unlimited_snapshot)
        allocation_sample = next(
            sample
            for sample in samples
            if sample.name == "warp_workspace_request_allocation_remaining"
        )

        self.assertTrue(math.isnan(allocation_sample.value))

    def test_snapshot_cache_preserves_last_success_on_failure(self) -> None:
        cache = warp_enterprise_exporter.SnapshotCache(
            sqlite_path="/tmp/warp.sqlite",
            preferences_plist_path="/tmp/dev.warp.Warp-Stable.plist",
            max_conversations=25,
            timeout=5,
            estimated_cents_per_credit=10.0,
        )

        with mock.patch.object(
            warp_enterprise_exporter.SnapshotCache,
            "load_snapshot",
            side_effect=[VALID_SNAPSHOT, RuntimeError("boom"), RuntimeError("boom")],
        ):
            success, error_message = cache.refresh()
            self.assertTrue(success)
            self.assertIsNone(error_message)

            success, error_message = cache.refresh()
            self.assertFalse(success)
            self.assertEqual(error_message, "boom")

            rendered, scrape_success, error_message = cache.render()

        self.assertFalse(scrape_success)
        self.assertEqual(error_message, "boom")
        self.assertIn("warp_conversation_model_estimated_spend_cents_total", rendered)
        self.assertIn("warp_exporter_scrape_success 0.0", rendered)


if __name__ == "__main__":
    unittest.main()
