#!/bin/sh
set -eu

mkdir -p "$(dirname "$WARP_USAGE_OUTPUT_PATH")" "$(dirname "$WARP_USAGE_STATE_PATH")"

python3 scripts/warp_usage_bridge.py &
bridge_pid="$!"

cleanup() {
  kill "$bridge_pid" 2>/dev/null || true
  wait "$bridge_pid" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

python3 scripts/warp_enterprise_exporter.py
