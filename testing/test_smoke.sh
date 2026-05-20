#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
SKIP_NETWORK_TESTS="${SKIP_NETWORK_TESTS:-0}"
RUN_API_KEY_TESTS="${RUN_API_KEY_TESTS:-1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

assert_status() {
  local expected="$1"
  local label="$2"
  if [[ "${RESPONSE_STATUS}" != "${expected}" ]]; then
    echo "FAIL: ${label} expected HTTP ${expected}, got ${RESPONSE_STATUS}"
    echo "Body: ${RESPONSE_BODY}"
    exit 1
  fi
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

echo "Running smoke test against: ${BASE_URL}"
BASE_URL="${BASE_URL}" "${SCRIPT_DIR}/test_health.sh"

echo "Testing openapi endpoint: ${BASE_URL}/openapi.json"
call_get "/openapi.json" "/openapi.json"
assert_status "200" "/openapi.json"
assert_body_contains '"openapi"[[:space:]]*:' "/openapi.json"

echo "Testing removed /search_web endpoint"
call_get "/search_web?query=fastapi&limit=1" "/search_web removed"
assert_status "404" "/search_web removed"

echo "Testing removed /search_google endpoint"
call_get "/search_google?query=fastapi&limit=1" "/search_google removed"
assert_status "404" "/search_google removed"

echo "Testing provider validation for /search_scholar"
call_get "/search_scholar?query=llm&provider=invalid_provider&limit=1" "/search_scholar invalid provider"
assert_status "400" "/search_scholar invalid provider"
assert_body_contains 'Invalid provider' "/search_scholar invalid provider"

if [[ "${SKIP_NETWORK_TESTS}" == "1" ]]; then
  echo "Skipping network-dependent tests (SKIP_NETWORK_TESTS=1)."
  if [[ "${RUN_API_KEY_TESTS}" == "1" ]]; then
    SKIP_NETWORK_TESTS="${SKIP_NETWORK_TESTS}" BASE_URL="${BASE_URL}" \
      "${SCRIPT_DIR}/test_api_keys.sh"
  fi
  echo "PASS: smoke test (non-network checks)"
  exit 0
fi

echo "Testing /fetch_page"
call_get "/fetch_page?url=https://example.com" "/fetch_page"
assert_status "200" "/fetch_page"
assert_body_contains '"title"[[:space:]]*:' "/fetch_page"

echo "Testing /review_page"
call_get "/review_page?url=https://example.com" "/review_page"
assert_status "200" "/review_page"
assert_body_contains '"word_count"[[:space:]]*:' "/review_page"

echo "Testing /search_scholar (semantic_scholar)"
call_get "/search_scholar?query=llm&provider=semantic_scholar&limit=2" "/search_scholar"
assert_status "200" "/search_scholar"
assert_body_contains '"provider"[[:space:]]*:[[:space:]]*"semantic_scholar"' "/search_scholar"

echo "Testing /download_pdf"
call_get "/download_pdf?url=https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf" "/download_pdf"
assert_status "200" "/download_pdf"
assert_body_contains '"filename"[[:space:]]*:' "/download_pdf"
assert_body_contains '"size_bytes"[[:space:]]*:' "/download_pdf"

if [[ "${RUN_API_KEY_TESTS}" == "1" ]]; then
  SKIP_NETWORK_TESTS="${SKIP_NETWORK_TESTS}" BASE_URL="${BASE_URL}" \
    "${SCRIPT_DIR}/test_api_keys.sh"
fi

echo "PASS: smoke test"
