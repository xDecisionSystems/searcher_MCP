#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
SKIP_NETWORK_TESTS="${SKIP_NETWORK_TESTS:-0}"
QUERY="${QUERY:-llm}"
LIMIT="${LIMIT:-2}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

RESPONSE_STATUS=""
RESPONSE_BODY=""

call_get() {
  local path="$1"
  local label="$2"
  local out_file="${TMP_DIR}/response.json"
  if ! RESPONSE_STATUS="$(curl -sS -o "${out_file}" -w "%{http_code}" "${BASE_URL}${path}")"; then
    echo "FAIL: ${label} request failed"
    exit 1
  fi
  RESPONSE_BODY="$(cat "${out_file}")"
}

assert_body_contains() {
  local pattern="$1"
  local label="$2"
  if ! grep -Eq "${pattern}" <<<"${RESPONSE_BODY}"; then
    echo "FAIL: ${label} response missing expected pattern: ${pattern}"
    echo "Body: ${RESPONSE_BODY}"
    exit 1
  fi
}

assert_ok_or_network_skip() {
  local label="$1"
  local provider="$2"

  if [[ "${RESPONSE_STATUS}" == "200" ]]; then
    assert_body_contains '"provider"[[:space:]]*:[[:space:]]*"'"${provider}"'"' "${label}"
    assert_body_contains '"results"[[:space:]]*:[[:space:]]*\[' "${label}"
    echo "PASS: ${label}"
    return
  fi

  if [[ "${RESPONSE_STATUS}" == "502" && "${SKIP_NETWORK_TESTS}" == "1" ]]; then
    echo "WARN: ${label} returned 502 while SKIP_NETWORK_TESTS=1; likely outbound network is blocked."
    return
  fi

  echo "FAIL: ${label} unexpected status ${RESPONSE_STATUS}"
  echo "Body: ${RESPONSE_BODY}"
  exit 1
}

echo "Running Semantic Scholar provider tests against: ${BASE_URL}"

call_get "/search_scholar?query=${QUERY}&provider=semantic_scholar&limit=${LIMIT}" "/search_scholar provider=semantic_scholar"
assert_ok_or_network_skip "/search_scholar provider=semantic_scholar" "semantic_scholar"

call_get "/search_scholar?query=${QUERY}&provider=auto&limit=${LIMIT}" "/search_scholar provider=auto"
assert_ok_or_network_skip "/search_scholar provider=auto" "semantic_scholar"

echo "PASS: Semantic Scholar provider tests"
