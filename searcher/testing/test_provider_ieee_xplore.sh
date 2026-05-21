#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
SKIP_NETWORK_TESTS="${SKIP_NETWORK_TESTS:-0}"
QUERY="${QUERY:-wireless+sensor+network}"
LIMIT="${LIMIT:-2}"
START_RECORD="${START_RECORD:-1}"

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

assert_keyed_or_ok_or_network_skip() {
  local label="$1"
  local provider="$2"

  if [[ "${RESPONSE_STATUS}" == "200" ]]; then
    assert_body_contains '"provider"[[:space:]]*:[[:space:]]*"'"${provider}"'"' "${label}"
    assert_body_contains '"results"[[:space:]]*:[[:space:]]*\[' "${label}"
    echo "PASS: ${label} key-configured behavior"
    return
  fi

  if [[ "${RESPONSE_STATUS}" == "400" ]]; then
    assert_body_contains 'IEEE_XPLORE_API_KEY is not configured' "${label}"
    echo "PASS: ${label} missing-key behavior"
    return
  fi

  if [[ "${RESPONSE_STATUS}" == "502" && "${SKIP_NETWORK_TESTS}" == "1" ]]; then
    echo "WARN: ${label} returned 502 while SKIP_NETWORK_TESTS=1; likely key is configured but outbound network is blocked."
    return
  fi

  echo "FAIL: ${label} unexpected status ${RESPONSE_STATUS}"
  echo "Body: ${RESPONSE_BODY}"
  exit 1
}

echo "Running IEEE Xplore provider tests against: ${BASE_URL}"

call_get "/search_ieeexplore?query=${QUERY}&limit=${LIMIT}&start_record=${START_RECORD}" "/search_ieeexplore"
assert_keyed_or_ok_or_network_skip "/search_ieeexplore" "ieeexplore"

call_get "/search_scholar?query=${QUERY}&provider=ieeexplore&limit=${LIMIT}&start_record=${START_RECORD}" "/search_scholar provider=ieeexplore"
assert_keyed_or_ok_or_network_skip "/search_scholar provider=ieeexplore" "ieeexplore"

echo "PASS: IEEE Xplore provider tests"
