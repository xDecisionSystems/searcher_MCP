# Searcher MCP (FastAPI)

FastAPI service for:

- Web search (`/search_web`)
- Direct Google search (`/search_google`)
- Webpage fetch + review-ready extraction (`/fetch_page`)
- Website review output (`/review_page`)
- Scholar search (`/search_scholar`)
- Direct Google Scholar search (`/search_google_scholar`)
- PDF download (`/download_pdf`)

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
cp .env.example .env
set -a && source .env && set +a
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Local testing docs URL:

- `http://127.0.0.1:8000/docs`

## 2. Update an Existing Proxmox Deployment

`update.sh` downloads the latest runtime files (including `app.py`, `requirements.txt`, `install.sh`, and `update.sh`) and restarts the service automatically.

```bash
SEARCHER_MCP_BASE_URL="https://raw.githubusercontent.com/xDecisionSystems/searcher_MCP/main" /opt/searcher_mcp/update.sh
```

## 3. Endpoints

### `GET /health`

Simple health check.

### `GET /search_web`

Params:

- `query` (required)
- `limit` (default `5`, max `20`)
- `provider` (`auto|serpapi_google|serper_google|brave|bing|duckduckgo`)

`auto` chooses `serpapi_google`, then `serper_google`, then `brave`, then `bing`, then `duckduckgo`.

### `GET /search_google`

Params:

- `query` (required)
- `limit` (default `5`, max `20`)

Uses SerpAPI Google when `SERPAPI_API_KEY` is set.
If `SERPAPI_API_KEY` is not set, it falls back to Serper Google (`SERPER_API_KEY` required).

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

### `GET /search_scholar`

Params:

- `query` (required)
- `limit` (default `5`, max `20`)
- `provider` (`auto|semantic_scholar|google_scholar_serpapi`)

`auto` uses Semantic Scholar.

### `GET /search_google_scholar`

Params:

- `query` (required)
- `limit` (default `5`, max `20`)

Always uses SerpAPI Google Scholar (`SERPAPI_API_KEY` required).

### `GET /download_pdf`

Params:

- `url` (required)

Downloads PDF to `DOWNLOAD_DIR` (or `/tmp` by default), enforces max size (`PDF_MAX_MB`), and returns file path + size.

## 4. Example Requests

```bash
curl "http://127.0.0.1:8000/search_web?query=fastapi+mcp&provider=duckduckgo"
curl "http://127.0.0.1:8000/search_google?query=fastapi+mcp"
curl "http://127.0.0.1:8000/fetch_page?url=https://example.com"
curl "http://127.0.0.1:8000/review_page?url=https://example.com"
curl "http://127.0.0.1:8000/search_scholar?query=llm+agents&provider=semantic_scholar"
curl "http://127.0.0.1:8000/search_google_scholar?query=retrieval+augmented+generation"
curl "http://127.0.0.1:8000/download_pdf?url=https://arxiv.org/pdf/1706.03762.pdf"
```
