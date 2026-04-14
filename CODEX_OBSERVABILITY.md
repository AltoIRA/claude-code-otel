# Codex CLI Observability

> Learn how to enable and configure OpenTelemetry for the OpenAI Codex CLI.

Codex CLI supports OpenTelemetry (OTel) traces and log events for monitoring and observability. Unlike Claude Code, which exports structured metrics (counters, histograms) and log events separately, Codex CLI exports **log events and traces only** — all telemetry data (including token usage) is embedded as structured metadata on log events.

> **Important:** Only the interactive `codex` CLI fully supports OTEL telemetry. `codex exec` emits traces and logs but **no metrics**, and `codex mcp-server` emits **no OTEL telemetry at all**.

## Quick Start

Configure OpenTelemetry by adding an `[otel]` section to `~/.codex/config.toml`:

```toml
[otel]
environment = "dev"

[otel.exporter.otlp-grpc]
endpoint = "http://localhost:4317"
```

Then run Codex normally:

```bash
codex
```

### Exporter Options

Codex supports the following exporter variants:

| Variant | Description |
| --- | --- |
| `otlp-grpc` | OTLP over gRPC (recommended for local collectors) |
| `otlp-http` | OTLP over HTTP |
| `none` | Disable OTEL export |

#### OTLP/HTTP example

```toml
[otel]
environment = "dev"

[otel.exporter.otlp-http]
endpoint = "http://localhost:4318"
protocol = "json"
```

#### With authentication headers

```toml
[otel]
environment = "dev"

[otel.exporter.otlp-grpc]
endpoint = "https://otel.company.com:4317"

[otel.exporter.otlp-grpc.headers]
Authorization = "Bearer your-token"
```

### Privacy

User prompt content can optionally be included in telemetry:

```toml
[otel]
environment = "dev"
log_user_prompt = false  # default: false
```

## Available Telemetry

### Event Types

Codex CLI exports the following event types via OpenTelemetry logs:

| Event Name | Description | Key Attributes |
| --- | --- | --- |
| `codex.conversation_starts` | A new conversation session begins | `conversation_id`, `model`, `sandbox_policy`, `approval_policy` |
| `codex.api_request` | An API request is made to OpenAI | `model`, `duration_ms`, `http_response_status_code`, `endpoint` |
| `codex.websocket_connect` | WebSocket connection established | `model` |
| `codex.websocket_request` | A request is sent over WebSocket | `model`, `duration_ms` |
| `codex.websocket_event` | A WebSocket event is received | `event_kind`, `model`, `duration_ms`, `success` |
| `codex.sse_event` | A Server-Sent Event is received | `event_kind`, `model` |

### Event Kinds

WebSocket and SSE events include an `event_kind` attribute describing the specific event:

| Event Kind | Description | Token Data? |
| --- | --- | --- |
| `response.completed` | Full API response completed | Yes |
| `response.created` | Response object created | No |
| `response.in_progress` | Response generation in progress | No |
| `response.output_item.added` | New output item started | No |
| `response.output_item.done` | Output item completed | No |
| `response.output_text.delta` | Streaming text chunk | No |
| `response.output_text.done` | Text output completed | No |
| `response.reasoning_summary_text.delta` | Streaming reasoning chunk | No |
| `response.reasoning_summary_text.done` | Reasoning output completed | No |
| `response.web_search_call.*` | Web search tool activity | No |

### Token Usage Attributes

Token counts are available on `response.completed` events as structured metadata:

| Attribute | Description |
| --- | --- |
| `input_token_count` | Number of input tokens consumed |
| `output_token_count` | Number of output tokens generated |
| `cached_token_count` | Number of tokens served from cache |
| `reasoning_token_count` | Number of tokens used for chain-of-thought reasoning |
| `tool_token_count` | Total tokens including tool call overhead |

### Standard Attributes (all events)

| Attribute | Description |
| --- | --- |
| `service_name` | Always `codex_cli_rs` |
| `service_version` | Codex CLI version |
| `app_version` | Codex CLI version |
| `model` | Model used (e.g., `gpt-5.2`) |
| `user_email` | User's email address |
| `user_account_id` | User's account identifier |
| `conversation_id` | Unique conversation identifier |
| `auth_mode` | Authentication mode (e.g., `Chatgpt`, `ApiKey`) |
| `originator` | Client type (e.g., `codex-tui`) |
| `terminal_type` | Terminal information |
| `env` | Environment tag from config |

## Cost Estimation

### How It Works

Unlike Claude Code, which emits a dedicated `claude_code.cost.usage` metric with pre-calculated USD costs, **Codex CLI does not emit cost data**. The dashboard estimates costs by multiplying token counts from `response.completed` events by per-token pricing rates.

The formula used is:

```
Estimated Cost = (input_tokens * input_price / 1M)
               + (cached_tokens * cached_price / 1M)
               + (output_tokens * output_price / 1M)
```

### Default Pricing

The dashboard uses GPT-5.4 standard API pricing as defaults:

| Token Type | Price per 1M tokens |
| --- | --- |
| Input | $2.50 |
| Cached Input | $0.25 |
| Output | $15.00 |

> **Note:** Reasoning tokens are billed at the output token rate by OpenAI but are tracked separately in the telemetry. The dashboard does not double-count them — `output_token_count` already includes reasoning tokens in the billing total.

### Important Caveats

1. **Subscription vs. API billing**: If you use `auth_mode = "Chatgpt"` (ChatGPT Plus/Pro/Enterprise subscription), you are drawing from a fixed allocation of requests/credits rather than paying per-token. The cost estimate still shows what the equivalent API cost _would be_, which is useful for tracking consumption intensity, but it does not reflect your actual bill.

2. **API Key billing**: If you use `auth_mode = "ApiKey"`, the cost estimate closely approximates your actual spend. Verify the per-token rates match your plan on the [OpenAI pricing page](https://openai.com/api/pricing/).

3. **Model-specific pricing**: Different models have different rates. If you use models other than GPT-5.4 (e.g., GPT-5.4-mini at $0.75/$4.50 per 1M), the default dashboard pricing will overestimate costs. To adjust, edit the pricing constants in the dashboard panel queries.

4. **Batch and Flex pricing**: OpenAI offers discounted batch ($1.25/$7.50) and flex ($1.25/$7.50) pricing tiers. The dashboard uses standard pricing — adjust if you use these tiers.

## Comparison with Claude Code Telemetry

| Feature | Claude Code | Codex CLI |
| --- | --- | --- |
| **Metrics export** | OTLP counters (Prometheus-compatible) | None — logs only |
| **Cost tracking** | Native `cost.usage` metric in USD | Estimated from token counts |
| **Token tracking** | Counter metric + log events | Log events only (structured metadata) |
| **Session tracking** | Counter metric | `codex.conversation_starts` log event |
| **Tool usage** | Per-tool name, success/failure, duration | Not emitted |
| **Lines of code** | Counter metric (added/removed) | Not emitted |
| **Commits/PRs** | Counter metrics | Not emitted |
| **API errors** | Dedicated `api_error` event with status code | Filter by `http_response_status_code` |
| **API duration** | `duration_ms` on `api_request` events | `duration_ms` on `api_request`/`websocket_request` events |
| **Configuration** | Environment variables | `~/.codex/config.toml` |
| **Service name** | `claude-code` | `codex_cli_rs` |

## Service Information

All telemetry is exported with:

* **Service Name**: `codex_cli_rs`
* **Telemetry SDK**: `opentelemetry` (Rust)
* **Scope Name**: `codex_otel.log_only`

## Querying in Grafana

### Loki (Log Events)

```logql
# All Codex events
{service_name="codex_cli_rs"}

# API completions with token counts
{service_name="codex_cli_rs"} | event_kind = "response.completed"

# Token usage (unwrap for numeric aggregation)
sum(sum_over_time({service_name="codex_cli_rs"} | input_token_count != "" | unwrap input_token_count [1h]))

# Error events
{service_name="codex_cli_rs"} | http_response_status_code != "" | http_response_status_code != "200"
```

### Prometheus

Codex CLI does not export Prometheus-compatible metrics. All data is queried via Loki.

## Security/Privacy Considerations

* Telemetry is opt-in and requires explicit configuration in `config.toml`
* User prompt content is not included by default (`log_user_prompt = false`)
* `user_email` and `user_account_id` are included in all events — consider this when sending telemetry to shared backends
* Source code content is never included in telemetry events
