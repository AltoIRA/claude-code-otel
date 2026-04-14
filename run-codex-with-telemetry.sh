#!/usr/bin/env bash
set -euo pipefail

if ! command -v codex >/dev/null 2>&1; then
  echo "codex was not found in PATH" >&2
  exit 1
fi

CONFIG_DIR="${HOME}/.codex"
CONFIG_FILE="${CONFIG_DIR}/config.toml"

OTEL_BLOCK='[otel]
environment = "dev"

[otel.exporter.otlp_grpc]
endpoint = "http://localhost:4317"'

if [ -f "$CONFIG_FILE" ] && grep -q '\[otel\]' "$CONFIG_FILE"; then
  echo "OTEL config already present in $CONFIG_FILE"
else
  mkdir -p "$CONFIG_DIR"
  printf '\n%s\n' "$OTEL_BLOCK" >> "$CONFIG_FILE"
  echo "Added OTEL config to $CONFIG_FILE"
fi

exec codex "$@"
