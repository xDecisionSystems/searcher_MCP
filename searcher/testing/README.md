# Testing Scripts

This folder contains shell scripts for local and deployed service testing.

## Scripts

- `testing/test_health.sh`
  - Verifies `/health` responds with `status=ok` and a `version_name`.
- `testing/test_smoke.sh`
  - Runs a broader smoke test against key endpoints.
  - Includes network-dependent checks by default.
- `testing/test_api_keys.sh`
  - Verifies API-key endpoint behavior.
  - Passes for either:
    - expected "key not configured" responses, or
    - successful responses when keys are configured.
- `testing/test_provider_semantic_scholar.sh`
  - Tests Semantic Scholar via `/search_scholar` with `provider=semantic_scholar` and `provider=auto`.
- `testing/test_provider_google_scholar.sh`
  - Tests Google Scholar (SerpAPI) via `/search_google_scholar` and `/search_scholar?provider=google_scholar_serpapi`.
- `testing/test_provider_ieee_xplore.sh`
  - Tests IEEE Xplore via `/search_ieeexplore` and `/search_scholar?provider=ieeexplore`.
- `testing/test_provider_scopus.sh`
  - Tests Elsevier Scopus via `/search_scopus` and `/search_scholar?provider=scopus`.
- `testing/test_local_deploy.sh`
  - Starts the API locally with `.venv`, runs smoke checks, then stops the server.

## Usage

Run against an already-running service:

```bash
BASE_URL="http://127.0.0.1:8000" ./testing/test_health.sh
BASE_URL="http://127.0.0.1:8000" ./testing/test_smoke.sh
BASE_URL="http://127.0.0.1:8000" ./testing/test_api_keys.sh
BASE_URL="http://127.0.0.1:8000" ./testing/test_provider_semantic_scholar.sh
BASE_URL="http://127.0.0.1:8000" ./testing/test_provider_google_scholar.sh
BASE_URL="http://127.0.0.1:8000" ./testing/test_provider_ieee_xplore.sh
BASE_URL="http://127.0.0.1:8000" ./testing/test_provider_scopus.sh
```

Skip network-dependent tests:

```bash
SKIP_NETWORK_TESTS=1 BASE_URL="http://127.0.0.1:8000" ./testing/test_smoke.sh
SKIP_NETWORK_TESTS=1 BASE_URL="http://127.0.0.1:8000" ./testing/test_provider_semantic_scholar.sh
SKIP_NETWORK_TESTS=1 BASE_URL="http://127.0.0.1:8000" ./testing/test_provider_google_scholar.sh
SKIP_NETWORK_TESTS=1 BASE_URL="http://127.0.0.1:8000" ./testing/test_provider_ieee_xplore.sh
SKIP_NETWORK_TESTS=1 BASE_URL="http://127.0.0.1:8000" ./testing/test_provider_scopus.sh
```

Skip API key tests during smoke run:

```bash
RUN_API_KEY_TESTS=0 BASE_URL="http://127.0.0.1:8000" ./testing/test_smoke.sh
```

Start local app and test automatically:

```bash
./testing/test_local_deploy.sh
```

The local deploy script loads `.env.dev` by default.
Override env file path with:

```bash
LOCAL_ENV_FILE="/path/to/custom.env" ./testing/test_local_deploy.sh
```
