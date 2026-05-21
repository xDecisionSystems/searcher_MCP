#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

echo "Testing health endpoint: ${BASE_URL}/health"
response="$(curl -fsS "${BASE_URL}/health")"

if ! grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"' <<<"${response}"; then
  echo "FAIL: /health did not include status=ok"
  echo "Response: ${response}"
  exit 1
fi

if ! grep -Eq '"version_name"[[:space:]]*:[[:space:]]*"' <<<"${response}"; then
  echo "FAIL: /health did not include version_name"
  echo "Response: ${response}"
  exit 1
fi

echo "PASS: health endpoint"
