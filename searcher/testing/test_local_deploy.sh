#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
BASE_URL="${BASE_URL:-http://${APP_HOST}:${APP_PORT}}"
SKIP_NETWORK_TESTS="${SKIP_NETWORK_TESTS:-0}"
RUN_API_KEY_TESTS="${RUN_API_KEY_TESTS:-1}"
LOG_FILE="${PROJECT_ROOT}/testing/local_server.log"
LOCAL_ENV_FILE="${LOCAL_ENV_FILE:-${PROJECT_ROOT}/.env.dev}"
VENV_PYTHON="${PROJECT_ROOT}/.venv/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]] && [[ -x "${PROJECT_ROOT}/../.venv/bin/python" ]]; then
  VENV_PYTHON="${PROJECT_ROOT}/../.venv/bin/python"
fi

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "FAIL: .venv is missing. Create it first and install dependencies."
  exit 1
fi

if [[ -f "${LOCAL_ENV_FILE}" ]]; then
  echo "Loading local environment: ${LOCAL_ENV_FILE}"
  set -a
  # shellcheck disable=SC1090
  source "${LOCAL_ENV_FILE}"
  set +a
else
  echo "WARN: ${LOCAL_ENV_FILE} not found. Continuing without env file."
fi

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "${SERVER_PID}" >/dev/null 2>&1; then
    kill "${SERVER_PID}" >/dev/null 2>&1 || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "Starting local API on ${BASE_URL}"
"${VENV_PYTHON}" -m uvicorn app:app \
  --host "${APP_HOST}" \
  --port "${APP_PORT}" \
  --app-dir "${PROJECT_ROOT}" \
  >"${LOG_FILE}" 2>&1 &
SERVER_PID=$!

echo "Waiting for API startup..."
for _ in $(seq 1 40); do
  if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

if ! curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
  echo "FAIL: local API did not become ready."
  echo "See logs: ${LOG_FILE}"
  exit 1
fi

echo "Running smoke tests..."
BASE_URL="${BASE_URL}" SKIP_NETWORK_TESTS="${SKIP_NETWORK_TESTS}" RUN_API_KEY_TESTS="${RUN_API_KEY_TESTS}" \
  "${PROJECT_ROOT}/testing/test_smoke.sh"

echo "PASS: local deployment test"
