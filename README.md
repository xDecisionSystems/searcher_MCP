# Searcher MCP (FastAPI)

FastAPI service for:

- Scholar search (`/search_scholar`)
- Direct Google Scholar search (`/search_google_scholar`)
- IEEE Xplore search (`/search_ieeexplore`)
- Web of Science search (`/search_web_of_science`)
- Webpage fetch + review-ready extraction (`/fetch_page`)
- Website review output (`/review_page`)
- PDF download (`/download_pdf`)

This service is intentionally scholar-focused and does not provide normal Google/Bing/Brave web search endpoints.

## 0. One-Line Proxmox LXC Installer (wget)

```bash
wget -O install.sh https://raw.githubusercontent.com/xDecisionSystems/searcher_MCP/main/install.sh && chmod +x install.sh && SEARCHER_MCP_BASE_URL="https://raw.githubusercontent.com/xDecisionSystems/searcher_MCP/main" ./install.sh
```

This installer downloads, installs, and deploys the FastAPI service on Debian-based Proxmox LXC, and installs `curl` as part of system dependencies.

## 1. Supported Deployment Targets

Supported deployment modes:

- Production: Debian-based Proxmox LXC with `systemd` (`searcher-mcp.service`)
- Testing: local deployment using `.venv` + `uvicorn`

After install, edit `/opt/searcher_mcp/.env` and add your API keys.

Swagger docs:

- `http://<lxc-ip>:8000/docs`

## 1b. Local Deployment (Testing Only)

```bash
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env.dev
set -a && source .env.dev && set +a
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Local testing docs URL:

- `http://127.0.0.1:8000/docs`

## 2. Update an Existing Proxmox Deployment

`update.sh` downloads the latest runtime files (including `app.py`, `requirements.txt`, `install.sh`, and `update.sh`) and restarts the service automatically.

```bash
SEARCHER_MCP_BASE_URL="https://raw.githubusercontent.com/xDecisionSystems/searcher_MCP/main" /opt/searcher_mcp/update.sh
```

## 3. Testing Scripts

The `testing/` folder includes endpoint smoke tests:

- `./testing/test_health.sh`
- `./testing/test_smoke.sh`
- `./testing/test_api_keys.sh`
- `./testing/test_local_deploy.sh`

See [testing/README.md](/home/aev/UCF Dropbox/Adan Vela/git-ucf/searcher_MCP/testing/README.md) for options and usage.

## 4. Environment Variables

Core provider keys:

- `SEMANTIC_SCHOLAR_API_KEY` (optional)
- `SERPAPI_API_KEY` (required for Google Scholar endpoints)
- `IEEE_XPLORE_API_KEY` (required for IEEE Xplore endpoints)
- `WEB_OF_SCIENCE_API_KEY` (required for Web of Science endpoints)

Runtime tuning:

- `REQUEST_TIMEOUT_SECONDS`
- `PDF_MAX_MB`
- `DOWNLOAD_DIR`
- `MCP_USER_AGENT`

## 5. Endpoints

### `GET /health`

Simple health check.

### `GET /search_scholar`

Params:

- `query` (required)
- `limit` (default `5`, max `20`)
- `provider` (`auto|semantic_scholar|google_scholar_serpapi|ieeexplore|web_of_science`)
- `start_record` (default `1`, IEEE Xplore only)
- `wos_page` (default `1`, Web of Science only)

`auto` chooses `semantic_scholar`.

### `GET /search_google_scholar`

Params:

- `query` (required)
- `limit` (default `5`, max `20`)

Uses SerpAPI Google Scholar (`SERPAPI_API_KEY` required).

### `GET /search_ieeexplore`

Params:

- `query` (required)
- `limit` (default `5`, max `20`)
- `start_record` (default `1`)

Uses IEEE Xplore Metadata API (`IEEE_XPLORE_API_KEY` required).

### `GET /search_web_of_science`

Params:

- `query` (required)
- `limit` (default `5`, max `20`)
- `page` (default `1`)

Uses Clarivate Web of Science Starter API (`WEB_OF_SCIENCE_API_KEY` required).

### `GET /fetch_page`

Params:

- `url` (required, must be `http(s)`)
- `include_html` (default `false`)
- `max_chars` (default `12000`)

Returns title, meta description, cleaned text, and up to 25 links.

### `GET /review_page`

Params:

- `url` (required, must be `http(s)`)
- `include_html` (default `false`)
- `max_chars` (default `12000`)

Returns everything from `/fetch_page` plus headings, word count, and estimated read time.

### `GET /download_pdf`

Params:

- `url` (required)

Downloads PDF to `DOWNLOAD_DIR` (or `/tmp` by default), enforces max size (`PDF_MAX_MB`), and returns file path + size.

## 6. Example Requests

```bash
curl "http://127.0.0.1:8000/search_scholar?query=llm+agents&provider=semantic_scholar"
curl "http://127.0.0.1:8000/search_scholar?query=retrieval+augmented+generation&provider=google_scholar_serpapi"
curl "http://127.0.0.1:8000/search_google_scholar?query=multi+agent+systems"
curl "http://127.0.0.1:8000/search_ieeexplore?query=wireless+sensor+network"
curl "http://127.0.0.1:8000/search_web_of_science?query=aviation+noise+model"
curl "http://127.0.0.1:8000/fetch_page?url=https://example.com"
curl "http://127.0.0.1:8000/review_page?url=https://example.com"
curl "http://127.0.0.1:8000/download_pdf?url=https://arxiv.org/pdf/1706.03762.pdf"
```
