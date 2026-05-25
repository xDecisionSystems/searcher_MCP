# searcher

FastAPI service for scholarly search and web content retrieval. Part of the `searcher-stack` deployment.

## Endpoints

- `GET /health` — liveness check
- `GET /search_scholar` — unified search across all providers
- `GET /search_google_scholar` — Google Scholar via scholarly library
- `GET /search_google_scholar_browser` — Google Scholar via real Chromium browser (CAPTCHA-resistant)
- `GET /search_ieeexplore` — IEEE Xplore (direct API)
- `GET /search_web_of_science` — Clarivate Web of Science (direct API)
- `GET /search_scopus` — Elsevier Scopus (direct API)
- `GET /fetch_page` — fetch and extract web page content
- `GET /review_page` — fetch page with headings, word count, read time
- `GET /download_pdf` — stream PDF to disk with size enforcement

## `search_google_scholar` Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `query` | required | Search query string |
| `limit` | 200 | Number of results to return |
| `start_index` | 0 | Result offset for pagination |
| `year_low` | — | Earliest publication year (inclusive) |
| `year_high` | — | Latest publication year (inclusive) |
| `exclude_domains` | — | Domains to exclude from results (defaults to `researchgate.net`, `books.google.com`, `search.proquest.com`) |

`search_google_scholar_browser` accepts the same parameters and returns results in the same schema, but uses the persistent Chromium browser. Prefer this when the scholarly library hits CAPTCHA blocks.

## Deployment

- Working directory inside LXC: `/opt/searcher/searcher`
- Env file: `/opt/searcher/.env` (shared with all services)
- Service: `searcher-mcp.service`
- Port: `8000`
- Swagger docs: `http://<lxc-ip>:8000/docs`

To update a live deployment:
```bash
pct exec <vmid> -- bash /opt/searcher/deploy/update.sh
```

## Local Testing

```bash
cd searcher
set -a && source ../.env.dev && set +a
../.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Docs: `http://127.0.0.1:8000/docs`

Syntax check:
```bash
../.venv/bin/python -m py_compile app.py searcher_mcp/*.py searcher_mcp/services/*.py
```

## Environment Variables

All keys are shared via the root `.env.example`. Provider keys:

- `SEMANTIC_SCHOLAR_API_KEY` (optional — unauthenticated access is rate-limited)
- `IEEE_XPLORE_API_KEY` (required for IEEE Xplore endpoints)
- `WEB_OF_SCIENCE_API_KEY` (required for Web of Science endpoints)
- `ELSEVIER_API_KEY` (required for Scopus endpoints)

Runtime tuning:

- `REQUEST_TIMEOUT_SECONDS` (default `20`)
- `PDF_MAX_MB` (default `50`)
- `DOWNLOAD_DIR` (default `/tmp`)
- `MCP_USER_AGENT`

## `/search_scholar` Provider Options

`provider` param: `auto` | `semantic_scholar` | `ieeexplore` | `web_of_science` | `scopus`

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
curl "http://127.0.0.1:8000/search_google_scholar?query=aviation+noise&limit=50&year_low=2020"
curl "http://127.0.0.1:8000/search_google_scholar?query=uav+manet&limit=200&exclude_domains=researchgate.net"
curl "http://127.0.0.1:8000/search_ieeexplore?query=llm+agents"
curl "http://127.0.0.1:8000/search_web_of_science?query=llm+agents"
curl "http://127.0.0.1:8000/search_scopus?query=llm+agents"
curl "http://127.0.0.1:8000/fetch_page?url=https://example.com"
curl "http://127.0.0.1:8000/review_page?url=https://example.com"
curl "http://127.0.0.1:8000/download_pdf?url=https://arxiv.org/pdf/1706.03762.pdf"
```
