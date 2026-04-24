# AI Coding Agent Observability Stack

[![GitHub](https://img.shields.io/badge/GitHub-ColeMurray%2Fclaude--code--otel-blue?logo=github)](https://github.com/ColeMurray/claude-code-otel)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue?logo=docker)](docker-compose.yml)

A comprehensive observability solution for monitoring AI coding agent usage, performance, and costs. Supports **Claude Code**, **Codex CLI**, and **Warp** out of the box, with separate dashboards tailored to each tool's telemetry schema.

## 🤖 Supported Agents

| Agent | Metrics | Log Events | Cost Tracking | Dashboard |
|-------|---------|------------|---------------|-----------|
| **Claude Code** | ✅ Native (Prometheus) | ✅ Native (Loki) | ✅ Native USD | [Claude Code Observability](CLAUDE_OBSERVABILITY.md) |
| **Codex CLI** | ❌ Logs only | ✅ Native (Loki) | ⚠️ Estimated from tokens | [Codex Observability](CODEX_OBSERVABILITY.md) |
| **Warp Enterprise** | ✅ Host exporter (Prometheus) | ✅ Local bridge (Loki) | ⚠️ Estimated from local credits | [Warp Enterprise Observability](WARP_OBSERVABILITY.md) |

## 📸 Dashboard Screenshots

### 💰 Cost & Usage Analysis
Track spending across different models with detailed breakdowns of costs, API requests, and token usage patterns.

<img src="docs/images/cost-usage-analytics.png" alt="Cost & Usage Analysis Dashboard" width="800">

*Features: Model cost comparison, API request tracking, token usage breakdown by type*

### 📊 User Activity & Productivity
Monitor development productivity with comprehensive session analytics, tool usage patterns, and code change metrics.

<img src="docs/images/user-activity.png" alt="User Activity & Productivity Dashboard" width="800">

*Features: Session tracking, tool performance metrics, code productivity insights*

## 🎯 Features

### 📊 **Comprehensive Monitoring**
- **Cost Analysis**: Track usage costs by model, user, and time periods
- **Token Usage**: Input, output, cached, and reasoning token breakdowns
- **Performance Metrics**: API latency and error rate tracking
- **Session Analytics**: Activity by conversation and user
- **Real-time Monitoring**: Live dashboards with 30-second refresh rates

### 🤖 **Multi-Agent Support**
- **Claude Code**: Full metrics + events with native cost and tool usage data
- **Codex CLI**: Log-event-based telemetry with estimated cost from token counts
- **Warp Enterprise**: Local usage events plus local enterprise context from Warp state
- All agents share the same collector, Prometheus, Loki, and Grafana stack

## 🏗️ Architecture

```
Claude Code     ──┐
Codex CLI       ──┼──▶ OpenTelemetry Collector ──▶ Prometheus (metrics)
Warp Usage Bridge──┤                            └──▶ Loki (log events)
Warp Exporter   ───┘
                                                         │
                                                  Grafana (visualization)
```

### Components

| Service | Purpose | Port | UI |
|---------|---------|------|----|
| **OpenTelemetry Collector** | Metrics/logs/traces ingestion | 4317 (gRPC), 4318 (HTTP) | - |
| **Prometheus** | Metrics storage & querying | 9090 | http://localhost:9090 |
| **Loki** | Log aggregation & storage | 3100 | - |
| **Grafana** | Dashboards & visualization | 3000 | http://localhost:3000 |

## 🚀 Quick Start

### 1. Start the Stack
```bash
make up
make status
```

### 2. Configure Your Agent

#### Claude Code
Add these to your `~/.zshrc` (or equivalent):

```bash
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=grpc
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Optional: faster intervals for local debugging
export OTEL_METRIC_EXPORT_INTERVAL=10000
export OTEL_LOGS_EXPORT_INTERVAL=5000
```

Then run `claude` normally. See `make setup-claude` for a reminder.

#### Codex CLI
Add this to `~/.codex/config.toml`:

```toml
[otel]
environment = "dev"

[otel.exporter.otlp-grpc]
endpoint = "http://localhost:4317"
```

Then run `codex` normally. See `make setup-codex` for a reminder.

#### Warp Enterprise
Run `make setup-warp` for the required host-side bridge/exporter environment variables, then start:

```bash
make run-warp-usage-bridge
make run-warp-enterprise-exporter
```

By default, the exporter reads Warp's local macOS state from `warp.sqlite` and `dev.warp.Warp-Stable.plist`. That base setup gives you real request, conversation, token, and tool metrics plus estimated spend using `WARP_ESTIMATED_CENTS_PER_CREDIT`, which currently defaults to a temporary `1.5` cents-per-credit guess until the actual Enterprise rate is known. It does not provide authoritative billed USD or purchased-credit tracking. See [WARP_OBSERVABILITY.md](WARP_OBSERVABILITY.md) for the exact data sources and limits.

### 3. Access Dashboards
- **Grafana**: http://localhost:3000 (admin/admin)
  - [Claude Code Observability](http://localhost:3000/d/claude-code-obs)
  - [Codex CLI Observability](http://localhost:3000/d/codex-cli-obs)
  - [Warp Enterprise Observability](http://localhost:3000/d/warp-enterprise-obs)
- **Prometheus**: http://localhost:9090

## 📊 Available Telemetry

### Claude Code

Full reference: [CLAUDE_OBSERVABILITY.md](CLAUDE_OBSERVABILITY.md)

**Metrics (Prometheus):**
- `claude_code.session.count` — CLI sessions started
- `claude_code.cost.usage` — Cost per session by model (USD)
- `claude_code.token.usage` — Tokens used (input/output/cacheRead/cacheCreation)
- `claude_code.lines_of_code.count` — Lines added/removed
- `claude_code.commit.count` / `claude_code.pull_request.count` — Dev activity
- `claude_code.code_edit_tool.decision` — Tool permission decisions

**Log Events (Loki, `service_name="claude-code"`):**
- `claude_code.user_prompt` — Prompt submissions
- `claude_code.tool_result` — Tool execution with success/failure, duration
- `claude_code.api_request` — API calls with token counts and cost
- `claude_code.api_error` — API errors with status codes
- `claude_code.tool_decision` — Tool permission decisions

### Codex CLI

Full reference: [CODEX_OBSERVABILITY.md](CODEX_OBSERVABILITY.md)

**Log Events (Loki, `service_name=~"codex_cli_rs|codex-app-server"`):**
- `codex.conversation_starts` — Session started
- `codex.api_request` — HTTP API calls with duration and status
- `codex.websocket_request` / `codex.websocket_event` — WebSocket activity
- `codex.sse_event` — Server-Sent Events with token counts on `response.completed`

Current Codex builds emit `service_name="codex-app-server"`. Older releases emitted `service_name="codex_cli_rs"`, and the dashboard now matches both.

**Token attributes on `response.completed` events:**
- `input_token_count`, `output_token_count`, `cached_token_count`, `reasoning_token_count`

> **Note:** Codex CLI does not emit Prometheus metrics. All Codex data is queried via Loki.

### Warp Enterprise

Full reference: [WARP_OBSERVABILITY.md](WARP_OBSERVABILITY.md)

**Metrics (Prometheus via host exporter):**
- `warp_workspace_*` — Workspace request allocation, refresh-window state, and cached enterprise billing controls
- `warp_member_*` — Current-user member request usage and request limits from local Warp state
- `warp_model_*` — Workspace model credit/request multipliers
- `warp_conversation_*` — Conversation credits, token totals, and tool usage totals
- `warp_estimated_*` — Estimated spend inputs and per-model estimated spend totals
- `warp_exporter_*` — Exporter health and last successful snapshot timestamp

**Log Events (Loki, `service_name="warp"`):**
- `AgentMode.CreatedAIBlock` — Warp AI response blocks
- `AIAutonomy.AutoexecutedRequestedCommand` — Auto-run terminal actions
- `AgentMode.Code.SuggestedEditReceived` / `AgentMode.Code.SuggestedEditResolved` — Suggested edit lifecycle
- `Block Creation` with `is_in_agent_view=true` — Agent-view block creation events

## 📋 Dashboard Sections

All dashboards follow the same layout for easy comparison:

Warp now mirrors the Codex dashboard layout closely. Its cost and token panels filter local snapshot data by conversation update time using the temporary `1.5` cents-per-credit default unless overridden, while its final enterprise row shows the cached workspace context available from local Warp state.

### 📊 Overview
Key stats for the last hour: sessions, cost, token usage, API requests.

### 💰 Cost & Usage Analysis
Cost trends by model, token usage rate by type, API requests by model.

> **Codex cost note:** Codex does not emit native cost data. The dashboard estimates cost by multiplying token counts from `response.completed` events by GPT-5.4 standard pricing ($2.50/$0.25/$15.00 per 1M input/cached/output tokens). If you use a ChatGPT subscription rather than direct API billing, these figures represent equivalent API cost rather than your actual spend. See [CODEX_OBSERVABILITY.md](CODEX_OBSERVABILITY.md) for full details.

### 🔧 Tool Usage / Event Activity
- **Claude Code**: Per-tool usage rate, cumulative usage, success rates
- **Codex**: Event rate by type and kind (websocket, SSE, etc.)

### ⚡ Performance & Errors
API request duration by model, API error rate by HTTP status code.

### 👤 Session Details / User Activity
- **Claude Code**: Code changes rate, commits and PRs
- **Codex**: Activity by conversation, token usage by user
- **Warp**: Conversation credits/tokens, estimated spend, and cached enterprise context

### 🔍 Event Logs
Formatted real-time log panels for API requests and errors.

## 🛠️ Management Commands

```bash
# Stack management
make up                  # Start all services
make down                # Stop all services
make restart             # Restart services
make clean               # Clean up containers and volumes

# Monitoring
make logs                # View all service logs
make logs-collector      # View collector logs
make logs-grafana        # View Grafana logs
make status              # Show service status and URLs

# Agent setup
make setup-claude        # Show Claude Code env var setup instructions
make setup-codex         # Show Codex CLI config.toml setup instructions
make setup-warp          # Show Warp Enterprise bridge/exporter setup instructions
make run-claude          # Launch Claude Code with telemetry configured
make run-codex           # Launch Codex CLI with telemetry configured
make run-warp-usage-bridge        # Tail warp_network.log into normalized NDJSON
make run-warp-enterprise-exporter # Serve Warp enterprise Prometheus metrics from local state
make run-warp-bridges             # Run both Warp host-side processes together

# Validation
make validate-config     # Validate docker-compose and collector config
make test                # Run unit tests
```

## 🔧 Advanced Configuration

### Collector

The OpenTelemetry Collector (`collector-config.yaml`) accepts any OTLP data on ports 4317 (gRPC) and 4318 (HTTP). Both Claude Code and Codex telemetry flow through the same collector with separate pipelines for metrics, logs, and traces.

Warp uses the same stack, but with a host-side usage bridge that writes normalized NDJSON for the collector's `filelog` receiver and a host-side exporter that serves Prometheus metrics directly.

### Adding More Agents

Any OTLP-compatible agent can send data to this stack. Point it at `localhost:4317` (gRPC) or `localhost:4318` (HTTP). Prometheus metrics appear automatically; logs appear in Loki queryable by `service_name`.

Agents without native OTLP support can still fit this repo's shape by adding a small host-side bridge/exporter pair, which is how Warp Enterprise support is implemented here.

### Alternative Stack

A lightweight single-container alternative using Grafana's LGTM image is available:

```bash
docker compose -f docker-compose-lgtm.yml up -d
```

## 🎯 Use Cases

### For Engineering Teams
- **Cost Management**: Track AI assistance costs by model, user, and time period
- **Tool Adoption**: Understand which agent features drive value
- **Performance Optimization**: Identify API latency bottlenecks

### For Platform Teams
- **Capacity Planning**: Predict infrastructure needs based on usage trends
- **Multi-Agent Visibility**: Unified view across Claude Code, Codex CLI, and Warp
- **SLA Monitoring**: Track API performance and error rates

### For Management
- **ROI Analysis**: Measure productivity gains from AI assistance
- **Usage Insights**: Understand adoption patterns across teams
- **Cost Control**: Monitor and optimize AI tool spending

## 🔒 Security & Privacy

- **User Privacy**: Prompt content logging is disabled by default in all supported agents
- **Data Isolation**: All telemetry stays within your infrastructure
- **PII in telemetry**: Both agents include `user_email` in events — consider this when configuring shared backends
- **Access Control**: Configure Grafana authentication as needed for team environments

## 📚 Resources

- [Claude Code Observability Documentation](CLAUDE_OBSERVABILITY.md)
- [Codex CLI Observability Documentation](CODEX_OBSERVABILITY.md)
- [Warp Enterprise Observability Documentation](WARP_OBSERVABILITY.md)
- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [Loki Documentation](https://grafana.com/docs/loki/)

## 🤝 Contributing

1. Follow the metric/event naming conventions in the observability docs
2. Update the relevant dashboards and documentation for any new agent support
3. Test configurations before submitting changes
4. Ensure sensitive information is excluded from commits
5. Add new agent support by: configuring `~/.yourAgent/config`, creating a `yourAgent-dashboard.json`, mounting it in `docker-compose.yml`, and adding Makefile targets

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built following the [Claude Code Observability Documentation](CLAUDE_OBSERVABILITY.md)
- Codex CLI telemetry schema sourced from live telemetry inspection
- Uses OpenTelemetry standards for metrics, logs, and traces
- Implements industry best practices for observability stack architecture
