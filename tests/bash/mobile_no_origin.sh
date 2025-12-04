#!/usr/bin/env bash
# Simple sanity check: mobile/native or server-to-server calls (no Origin header) bypass CORS.
# Run while the API is serving on localhost:8000 (e.g., `make api-dev` or `make api-dev-emu`).

set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000/health}"

echo "Hitting ${API_URL} without Origin header..."
status=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}")

if [[ "$status" == "200" ]]; then
  echo "✅ No-Origin call succeeded (CORS not applied to non-browser clients)."
else
  echo "❌ Unexpected status ${status} (expected 200)."
  exit 1
fi
