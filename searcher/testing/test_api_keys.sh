#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
SKIP_NETWORK_TESTS="${SKIP_NETWORK_TESTS:-0}"

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

test_keyed_endpoint() {
  local path="$1"
  local label="$2"
  local missing_key_pattern="$3"

  call_get "${path}" "${label}"

  if [[ "${RESPONSE_STATUS}" == "400" ]]; then
    if grep -Eq "${missing_key_pattern}" <<<"${RESPONSE_BODY}"; then
      echo "PASS: ${label} missing-key behavior"
      return
    fi
    echo "FAIL: ${label} returned 400 but not expected key error"
    echo "Body: ${RESPONSE_BODY}"
    exit 1
  fi

  if [[ "${RESPONSE_STATUS}" == "200" ]]; then
    echo "PASS: ${label} key-configured behavior"
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

echo "Running API key behavior tests against: ${BASE_URL}"

test_keyed_endpoint \
  "/search_google_scholar?query=llm&limit=1" \
  "/search_google_scholar" \
  "SERPAPI_API_KEY is not configured"

test_keyed_endpoint \
  "/search_scholar?query=llm&provider=google_scholar_serpapi&limit=1" \
  "/search_scholar provider=google_scholar_serpapi" \
  "SERPAPI_API_KEY is not configured"

test_keyed_endpoint \
  "/search_ieeexplore?query=wireless+sensor+network&limit=1" \
  "/search_ieeexplore" \
  "IEEE_XPLORE_API_KEY is not configured"


echo "PASS: API key behavior tests"
