# Warp Enterprise Observability

> Feed local Warp usage activity and local enterprise context into the same Prometheus, Loki, and Grafana stack used by Claude Code and Codex.

Warp does not emit native OTLP metrics for the local desktop client, so this repo runs one Dockerized helper service named `warp-bridges`:

1. `scripts/warp_usage_bridge.py` tails Warp's local `warp_network.log` and writes normalized NDJSON events for Loki.
2. `scripts/warp_enterprise_exporter.py` reads Warp's local SQLite database and preferences plist directly, then exposes Prometheus metrics on `warp-bridges:9498` inside Docker.

Both scripts run in the same container. The container mounts Warp state read-only and only writes normalized bridge output under this repo's `./tmp` directory.

There is no external snapshot command path anymore. Base setup is local-state only.

## Quick Start

### 1. Start the stack with Warp bridges

```bash
make up-warp
```

This starts the normal observability stack plus the `warp-bridges` Compose profile.

### 2. Override Docker host mount paths if needed

The Dockerized setup uses these default macOS host paths:

```bash
export WARP_NETWORK_LOG_DIR="$HOME/Library/Application Support/dev.warp.Warp-Stable"
export WARP_SQLITE_DIR="$HOME/Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/dev.warp.Warp-Stable"
export WARP_PREFERENCES_PLIST_PATH="$HOME/Library/Preferences/dev.warp.Warp-Stable.plist"
```

If those paths already match your machine, you do not need to set them.

Inside the container those host paths are mapped to:

```bash
WARP_NETWORK_LOG_PATH=/warp-network/warp_network.log
WARP_SQLITE_PATH=/warp-state/warp.sqlite
WARP_PREFERENCES_PLIST_PATH=/warp-preferences/dev.warp.Warp-Stable.plist
```

Docker Desktop must be allowed to share the mounted host directories. The default `/Users/...` paths are normally shared on macOS Docker Desktop.

The exporter defaults estimated USD panels to `1.5` cents per credit. This is only a temporary guess until the actual Enterprise cents-per-credit value is confirmed.

Optional: override the guessed rate with your own manual cents-per-credit value:

```bash
export WARP_ESTIMATED_CENTS_PER_CREDIT="1.5"
```

For foreground logs during debugging:

```bash
make run-warp-bridges
```

For host-side debugging without Docker, the old individual helpers remain available:

```bash
make run-warp-bridges-host
make run-warp-usage-bridge
make run-warp-enterprise-exporter
```

## What the Base Setup Provides

The local-state setup is enough to drive a Warp dashboard that looks and behaves much more like the Claude Code and Codex dashboards.

### Real signals from local Warp state

- recent Warp interactions from `warp_network.log`
- selected workspace identity
- request-limit window state and next refresh time
- enterprise pricing/control flags cached locally
- current-user member request usage and role
- conversation credits spent
- Warp-managed token totals
- BYOK token totals
- tool usage totals
- feature-model credit and request multipliers

### Not available from base setup

- authoritative month-to-date USD spend
- purchased-credit history
- source-of-funds attribution
- workspace-wide cross-user activity beyond the local cache

Because of that, the dashboard does **not** show actual billed dollars. It shows an **estimate** using the current `WARP_ESTIMATED_CENTS_PER_CREDIT` value, which defaults to a temporary `1.5` cents-per-credit guess.

## Local Usage Events

`scripts/warp_usage_bridge.py` keeps only the event families used by the dashboard:

- `AgentMode.CreatedAIBlock`
- `AIAutonomy.AutoexecutedRequestedCommand`
- `AgentMode.Code.SuggestedEditReceived`
- `AgentMode.Code.SuggestedEditResolved`
- `Block Creation` when `is_in_agent_view=true`

The bridge writes one JSON object per line with these normalized fields when present:

- `service_name`
- `source`
- `event`
- `timestamp`
- `conversation_id`
- `client_exchange_id`
- `server_output_id`
- `model_id`
- `time_to_first_token_ms`
- `time_to_last_token_ms`
- `was_user_facing_error`
- `reason`
- `terminal_session_id`
- `session_id`
- `release_mode`

## Local Snapshot Data Sources

The exporter reads:

- `~/Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/dev.warp.Warp-Stable/warp.sqlite`
  - selected workspace identity
  - workspace billing metadata and tier policy
  - workspace settings such as usage-based pricing and add-on auto-reload
  - recent conversation credit, token, and tool usage
  - current user's role in the selected team
- `~/Library/Preferences/dev.warp.Warp-Stable.plist`
  - request-limit window state
  - next refresh time
  - available feature-model choices

This is a local-user-oriented enterprise context, not a full admin billing export.

## Estimated Spend

The exporter emits estimated-spend metrics using `WARP_ESTIMATED_CENTS_PER_CREDIT`. If the env var is unset, it uses the current temporary default of `1.5` cents per credit until the actual Enterprise rate is known.

- `warp_estimated_cents_per_credit`
- `warp_conversation_model_estimated_spend_cents_total`

The estimate is derived like this:

1. use each conversation's `credits_spent`
2. look only at `warp_token_usage` and ignore `byok_token_usage`
3. weight each model by `warp_tokens * credit_multiplier`
4. allocate conversation credits across models by that weighted share
5. convert credits to cents using `WARP_ESTIMATED_CENTS_PER_CREDIT`

Grafana filters token, credit, and estimated-spend panels by each conversation's `warp_conversation_last_updated_timestamp_seconds`, so the time picker reflects conversations updated inside the selected range. The exporter data is still a local Warp snapshot rather than an append-only counter.

## Dashboard Layout

The Warp dashboard now follows the same top-level structure as Codex as closely as the data allows:

- `📊 Overview`
- `💰 Cost & Usage Analysis`
- `🔧 Event Activity`
- `⚡ Performance & Errors`
- `👤 Session Details`
- `🔍 Event Logs`
- `💳 Enterprise Context`

The final enterprise row stays small and only shows base-setup context that is actually available from local state.

## Exported Metrics

The exporter publishes:

- `warp_workspace_requests_used_since_last_refresh`
- `warp_workspace_request_limit`
- `warp_workspace_request_allocation_remaining`
- `warp_workspace_current_period_end_timestamp_seconds`
- `warp_workspace_next_refresh_timestamp_seconds`
- `warp_workspace_bonus_grants_remaining`
- `warp_workspace_bonus_grants_total`
- `warp_workspace_current_month_requests_used`
- `warp_workspace_usage_based_pricing_enabled`
- `warp_workspace_usage_based_pricing_max_monthly_spend_cents`
- `warp_workspace_addon_auto_reload_enabled`
- `warp_workspace_addon_max_monthly_spend_cents`
- `warp_workspace_addon_selected_auto_reload_credit_denomination`
- `warp_workspace_enterprise_payg_enabled`
- `warp_workspace_enterprise_payg_cost_per_thousand_credits_cents`
- `warp_workspace_enterprise_auto_reload_enabled`
- `warp_workspace_enterprise_auto_reload_cost_cents`
- `warp_workspace_enterprise_auto_reload_credit_denomination`
- `warp_member_requests_used_since_last_refresh`
- `warp_member_request_limit`
- `warp_model_credit_multiplier`
- `warp_model_request_multiplier`
- `warp_conversation_credits_spent_total`
- `warp_conversation_last_updated_timestamp_seconds`
- `warp_conversation_tokens_total`
- `warp_conversation_tool_calls_total`
- `warp_exporter_scrape_success`
- `warp_exporter_snapshot_timestamp_seconds`

Estimated-spend metrics:

- `warp_estimated_cents_per_credit`
- `warp_conversation_model_estimated_spend_cents_total`

## Setup Checklist

From a clean machine:

1. Install and open Warp at least once so `warp_network.log`, `warp.sqlite`, and the preferences plist exist locally.
2. Run `make up-warp`.
3. Open `http://localhost:3000/d/warp-enterprise-obs`.

If you know the real Enterprise cents-per-credit rate, set `WARP_ESTIMATED_CENTS_PER_CREDIT` before step 2. Otherwise the exporter uses the temporary `1.5` cents-per-credit guess.

## Validation

Run the unit tests:

```bash
make test
```

Then validate the stack configuration:

```bash
make validate-config
docker compose config >/dev/null
```

Finally, confirm:

- Prometheus target `warp-enterprise-exporter` is up at `http://localhost:9090/targets`
- `tail -f tmp/warp-usage-events.ndjson`
- `docker compose --profile warp ps warp-bridges`
- Grafana Warp dashboard: `http://localhost:3000/d/warp-enterprise-obs`

## Current Limits

- The exporter reports the current Warp user's member usage, role, and request limit from local state. It does not reconstruct full team-wide per-member activity.
- Estimated USD is not Warp billing. It is only a manual-rate estimate derived from local credit burn, and the default `1.5` cents-per-credit rate is a temporary guess until the actual Enterprise value is confirmed.
- Purchased credits and authoritative billed dollars are intentionally omitted because the local Warp cache does not expose them reliably.
