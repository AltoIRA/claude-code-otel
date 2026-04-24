# AI Coding Agent Observability Stack
.PHONY: help up down logs restart clean validate-config status logs-collector logs-prometheus logs-grafana run-claude setup-codex run-codex setup-warp run-warp-usage-bridge run-warp-enterprise-exporter run-warp-bridges demo-metrics test

help: ## Show this help message
	@echo "AI Coding Agent Observability Stack"
	@echo "===================================="
	@echo ""
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

up: ## Start the observability stack
	@echo "🚀 Starting AI coding agent observability stack..."
	docker compose up -d
	@echo "✅ Stack started!"
	@echo "📊 Grafana: http://localhost:3000 (admin/admin)"
	@echo "🔍 Prometheus: http://localhost:9090"
	@echo "📄 Loki: http://localhost:3100"


down: ## Stop the observability stack
	@echo "🛑 Stopping AI coding agent observability stack..."
	docker compose down
	@echo "✅ Stack stopped!"

restart: ## Restart the observability stack
	@echo "🔄 Restarting AI coding agent observability stack..."
	docker compose restart
	@echo "✅ Stack restarted!"

logs: ## Show logs from all services
	docker compose logs -f

logs-collector: ## Show OpenTelemetry collector logs
	docker compose logs -f otel-collector

logs-prometheus: ## Show Prometheus logs
	docker compose logs -f prometheus

logs-grafana: ## Show Grafana logs
	docker compose logs -f grafana

test: ## Run unit tests
	python3 -m unittest discover -s tests -v

clean: ## Clean up containers and volumes
	@echo "🧹 Cleaning up..."
	docker compose down -v
	docker system prune -f
	@echo "✅ Cleanup complete!"





validate-config: ## Validate all configuration files
	@echo "✅ Validating configurations..."
	@echo "📋 Checking docker compose.yml..."
	docker compose config > /dev/null && echo "✅ docker compose.yml is valid"
	@echo "📋 Checking collector-config.yaml..."
	@if command -v otelcol-contrib >/dev/null 2>&1; then \
		otelcol-contrib --config-validate --config=collector-config.yaml; \
	else \
		echo "ℹ️  Install otelcol-contrib to validate collector config"; \
	fi


status: ## Show stack status
	@echo "📊 AI Coding Agent Observability Stack Status"
	@echo "============================================="
	@docker compose ps
	@echo ""
	@echo "🌐 Service URLs:"
	@echo "  Grafana:      http://localhost:3000"
	@echo "  Prometheus:   http://localhost:9090"
	@echo "  Loki:         http://localhost:3100"
	@echo "  Warp:         http://localhost:3000/d/warp-enterprise-obs"

	@echo "  Collector:    http://localhost:4317 (gRPC), http://localhost:4318 (HTTP)"

setup-claude: ## Display Claude Code telemetry setup instructions
	@echo "🤖 Claude Code Telemetry Setup"
	@echo "==============================="
	@echo ""
	@echo "To enable telemetry in Claude Code, set these environment variables:"
	@echo ""
	@echo "export CLAUDE_CODE_ENABLE_TELEMETRY=1"
	@echo "export OTEL_METRICS_EXPORTER=otlp"
	@echo "export OTEL_LOGS_EXPORTER=otlp"
	@echo "export OTEL_EXPORTER_OTLP_PROTOCOL=grpc"
	@echo "export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317"
	@echo ""
	@echo "For debugging (faster export intervals):"
	@echo "export OTEL_METRIC_EXPORT_INTERVAL=10000"
	@echo "export OTEL_LOGS_EXPORT_INTERVAL=5000"
	@echo ""
	@echo "Then run: claude"

run-claude: ## Launch Claude Code with telemetry pointed at the local stack
	@./run-claude-with-telemetry.sh

setup-codex: ## Display Codex CLI telemetry setup instructions
	@echo "🤖 Codex CLI Telemetry Setup"
	@echo "============================="
	@echo ""
	@echo "Add this to ~/.codex/config.toml:"
	@echo ""
	@echo "[otel]"
	@echo 'environment = "dev"'
	@echo ""
	@echo "[otel.exporter.otlp_grpc]"
	@echo 'endpoint = "http://localhost:4317"'
	@echo ""
	@echo "Then run: codex"
	@echo ""
	@echo "Note: Only interactive codex mode emits full OTEL telemetry."
	@echo "      codex exec and codex mcp-server have limited/no telemetry support."

run-codex: ## Launch Codex CLI with telemetry pointed at the local stack
	@./run-codex-with-telemetry.sh

setup-warp: ## Display Warp Enterprise telemetry setup instructions
	@echo "🤖 Warp Enterprise Observability Setup"
	@echo "======================================"
	@echo ""
	@echo "1. Start the stack:"
	@echo "   make up"
	@echo ""
	@echo "2. Export host-side bridge paths:"
	@echo '   export WARP_NETWORK_LOG_PATH="$$HOME/Library/Application Support/dev.warp.Warp-Stable/warp_network.log"'
	@echo '   export WARP_USAGE_OUTPUT_PATH="$(PWD)/tmp/warp-usage-events.ndjson"'
	@echo '   export WARP_USAGE_STATE_PATH="$(PWD)/tmp/warp-usage-bridge-state.json"'
	@echo ""
	@echo "3. Optional: override the default local file paths:"
	@echo '   export WARP_SQLITE_PATH="$$HOME/Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/dev.warp.Warp-Stable/warp.sqlite"'
	@echo '   export WARP_PREFERENCES_PLIST_PATH="$$HOME/Library/Preferences/dev.warp.Warp-Stable.plist"'
	@echo ""
	@echo "   Optional estimated spend override:"
	@echo '   export WARP_ESTIMATED_CENTS_PER_CREDIT="1.5"'
	@echo ""
	@echo "   The exporter defaults to 1.5 cents/credit as a temporary guess until the actual Enterprise rate is known."
	@echo ""
	@echo "4. Run the host-side bridges:"
	@echo "   make run-warp-usage-bridge"
	@echo "   make run-warp-enterprise-exporter"
	@echo ""
	@echo "5. Open the Warp dashboard:"
	@echo "   http://localhost:3000/d/warp-enterprise-obs"

run-warp-usage-bridge: ## Tail warp_network.log and emit normalized NDJSON events
	@python3 scripts/warp_usage_bridge.py

run-warp-enterprise-exporter: ## Serve Prometheus metrics from local Warp state
	@python3 scripts/warp_enterprise_exporter.py

run-warp-bridges: ## Run the Warp usage bridge and enterprise exporter together
	@python3 scripts/warp_usage_bridge.py & \
	BRIDGE_PID=$$!; \
	trap 'kill $$BRIDGE_PID' EXIT INT TERM; \
	python3 scripts/warp_enterprise_exporter.py

demo-metrics: ## Generate demo metrics for testing
	@echo "🎯 This would generate demo metrics if Claude Code was running"
	@echo "💡 To see real metrics, ensure Claude Code is configured with telemetry enabled"
	@echo "📖 Run 'make setup-claude' for setup instructions" 
