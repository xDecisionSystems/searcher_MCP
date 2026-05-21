# searcher

FastAPI service for scholarly search and web content retrieval. Part of the `searcher-stack` deployment.

## Endpoints

- `GET /health` — liveness check
- `GET /search_scholar` — unified search across all providers
- `GET /search_google_scholar` — SerpAPI Google Scholar (direct)
- `GET /search_ieeexplore` — IEEE Xplore (direct)
- `GET /search_web_of_science` — Clarivate Web of Science (direct)
- `GET /search_scopus` — Elsevier Scopus (direct)
- `GET /fetch_page` — fetch and extract web page content
- `GET /review_page` — fetch page with headings, word count, read time
- `GET /download_pdf` — stream PDF to disk with size enforcement

## Deployment

Deployed as part of the full stack via `deploy/proxmox_deploy.sh` at the repo root.

- Working directory inside LXC: `/opt/repo/searcher`
- Env file: `/opt/repo/.env` (shared with all services)
- Service: `searcher-mcp.service`
- Port: `8000`
- Swagger docs: `http://<lxc-ip>:8000/docs`

To update a live deployment:
```bash
pct exec <vmid> -- bash /opt/repo/deploy/update.sh
```

## Local Testing

```bash
cd searcher
set -a && source ../.env.dev && set +a
../.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Docs: `http://127.0.0.1:8000/docs`

## Environment Variables

All keys are shared via the root `.env.example`. Provider keys:

- `SEMANTIC_SCHOLAR_API_KEY` (optional — unauthenticated access is rate-limited)
- `SERPAPI_API_KEY` (required for Google Scholar endpoints)
- `IEEE_XPLORE_API_KEY` (required for IEEE Xplore endpoints)
- `WEB_OF_SCIENCE_API_KEY` (required for Web of Science endpoints)
- `ELSEVIER_API_KEY` (required for Scopus endpoints)

Runtime tuning:

- `REQUEST_TIMEOUT_SECONDS` (default `20`)
- `PDF_MAX_MB` (default `50`)
- `DOWNLOAD_DIR` (default `/tmp`)
- `MCP_USER_AGENT`

## `/search_scholar` Provider Options

`provider` param: `auto` | `semantic_scholar` | `google_scholar_serpapi` | `ieeexplore` | `web_of_science` | `scopus`

`auto` defaults to `semantic_scholar`. Semantic Scholar is throttled to 1 request/second (unauthenticated rate limit).

## Testing Scripts

```bash
./testing/test_health.sh
./testing/test_smoke.sh
./testing/test_api_keys.sh
./testing/test_local_deploy.sh
```

## Example Requests

```bash
curl "http://127.0.0.1:8000/search_scholar?query=llm+agents&provider=semantic_scholar"
curl "http://127.0.0.1:8000/search_scholar?query=llm+agents&provider=google_scholar_serpapi"
curl "http://127.0.0.1:8000/search_scholar?query=llm+agents&provider=ieeexplore"
curl "http://127.0.0.1:8000/search_scholar?query=llm+agents&provider=web_of_science"
curl "http://127.0.0.1:8000/search_scholar?query=llm+agents&provider=scopus"
curl "http://127.0.0.1:8000/fetch_page?url=https://example.com"
curl "http://127.0.0.1:8000/review_page?url=https://example.com"
curl "http://127.0.0.1:8000/download_pdf?url=https://arxiv.org/pdf/1706.03762.pdf"
```
