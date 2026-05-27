# searcher

Monorepo containing two FastAPI services and a browser stack deployed together in a single Proxmox LXC.

## Services

### [`searcher/`](searcher/)

FastAPI service for scholarly search and web content retrieval.

- Scholar search via Semantic Scholar, Google Scholar (browser-driven), IEEE Xplore, Web of Science, Scopus, ScienceDirect, and EBSCO
- Web page fetch and review-ready extraction
- Direct PDF download with size and content-type enforcement

### [`browser_worker/`](browser_worker/)

FastAPI service that drives a persistent Chromium browser to download papers from authenticated publisher portals.

- Navigates paper pages using domain-specific strategy files and downloads the PDF
- Handles institutional login detection — surfaces a prompt so the user can log in via noVNC
- Serializes downloads (one at a time) with a lock; returns `status=busy` if already busy
- Batch endpoint `/download_papers` processes a list of URLs sequentially, pausing on login/CAPTCHA
- Session cookies persist across calls — solving a CAPTCHA once covers subsequent requests

## Repository Layout

```
searcher/
├── searcher/                    # Scholar search FastAPI service (port 8000)
├── browser_worker/              # Browser-automation download FastAPI service (port 8010)
│   └── browser_worker/
│       └── strategies/          # Per-domain download strategy JSON files
├── deploy/                      # Stack-level deployment and operations scripts
│   ├── update.sh                # Updates code and restarts services in the LXC
│   └── restart.sh               # Restarts all services in dependency order
├── .env.example                 # Shared env template covering all services
├── VERSION.md                   # Stack version
├── AGENTS.md                    # Agent and contributor instructions
├── CLAUDE.md                    # Claude Code instructions
└── README.md                    # This file
```

## Deployment Overview

Both services run in a single Proxmox LXC alongside the browser stack.

| Service | Port | Description |
|---------|------|-------------|
| `searcher-mcp` | 8000 | Scholar search FastAPI |
| `browser-worker` | 8010 | Browser-download FastAPI |
| `novnc` | 6080 | Browser-based remote desktop (password protected) |
| `chromium-cdp` | 9222 (localhost) | Chromium with GUI on virtual display |
| `x11vnc` | 5900 (localhost) | VNC server on virtual display |
| `xvfb` | — | Virtual display :99 |

Deployed code lives at `/opt/searcher/` inside the LXC (a git clone of this repo).
A single shared `/opt/searcher/.env` covers all services — symlinked from each service directory.

---

## Using as MCP servers with Claude Code

Both services expose all their tools as MCP servers.

Add to your Claude Code MCP settings (`~/.claude/settings.json` or via `/config`):

```json
{
  "mcpServers": {
    "searcher": {
      "type": "http",
      "url": "https://searcher.xds-lab.com/aev/search/mcp"
    },
    "browser_worker": {
      "type": "http",
      "url": "https://searcher.xds-lab.com/aev/browser/mcp"
    }
  }
}
```

Available MCP tools for `searcher`: `search_semantic_scholar`, `search_google_scholar_browser`, `search_ieeexplore`, `search_web_of_science`, `search_scopus`, `search_sciencedirect`, `search_ebsco`, `download_ebsco_paper`, `download_ebsco_papers`, `fetch_page`, `review_page`, `download_pdf`.

Available MCP tools for `browser_worker`: `download_paper`, `download_papers`, `fetch_page`, `search_google_scholar`, `record_session`, `stop_recording`, `recording_status`, `list_strategies`, `get_strategy`, `put_strategy`, `delete_strategy`, `list_files`, `get_file`, `get_logs`.

---

## Operations

### Update existing deployment

```bash
pct exec <vmid> -- bash /opt/searcher/deploy/update.sh
```

### Restart all services

```bash
pct exec <vmid> -- bash /opt/searcher/deploy/restart.sh
```

### Log into publisher portals (ScienceDirect, IEEE, EBSCO, etc.)

1. Open `https://searcher.xds-lab.com/aev/novnc/vnc.html` in your browser
2. Enter your `VNC_PASSWORD`
3. A full Chromium browser appears — log in to the portal normally
4. Session is saved to `/opt/searcher/browser_worker/chromium-profile` — persists across restarts

---

## Searcher API — Endpoint Reference

**Base URL (production):** `https://searcher.xds-lab.com/aev/search`
**Base URL (local dev):** `http://127.0.0.1:8000`
**OpenAPI docs:** `<base>/docs`

All search endpoints return a common **envelope** (except `fetch_page`, `review_page`, `download_pdf`):

```json
{
  "provider": "ieeexplore",
  "query": "UAV trajectory optimization",
  "search_date": "2026-05-27",
  "total_records_available": 1842,
  "total_records_downloaded": 25,
  "results": [ ... ]
}
```

Each item in `results` has this **result record** shape:

```json
{
  "title": "Trajectory Optimization in UAV-Assisted Cellular Networks",
  "url": "https://ieeexplore.ieee.org/document/8714567/",
  "publication_year": 2019,
  "authors": ["Md Moin Uddin Chowdhury", "Eyuphan Bulut", "Ismail Guvenc"],
  "doi": "10.1109/RWS.2019.8714567",
  "source": "2019 IEEE Radio and Wireless Symposium (RWS)",
  "snippet": "Abstract text...",
  "pdf_link": "https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber=8714567"
}
```

Fields may be empty strings or `null` when unavailable; `authors` is always an array (possibly empty).

---

### `GET /health`

Returns service status and current version.

**Response:**
```json
{ "status": "ok", "version_name": "searcher-stack-v1.1.151" }
```

---

### `GET /search_semantic_scholar`

Search Semantic Scholar via their public API. Good for broad coverage of CS and STEM papers with citation data.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | **required** | Free-text search query |
| `limit` | int ≥ 1 | `10` | Maximum results to return |

**Example:**
```
GET /search_semantic_scholar?query=UAV+trajectory+optimization&limit=20
```

**Notes:**
- No API key required (optional `SEMANTIC_SCHOLAR_API_KEY` raises rate limits)
- Does not support Boolean operators or year filtering
- `total_records_available` reflects Semantic Scholar's reported total

---

### `GET /search_google_scholar_browser`

Search Google Scholar by driving the persistent Chromium browser. More reliable than library-based scrapers for high-volume queries.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | **required** | Search query |
| `limit` | int ≥ 1 | `200` | Maximum results to return |
| `start_index` | int ≥ 0 | `0` | Result offset for pagination |
| `year_low` | int | `null` | Earliest publication year (inclusive) |
| `year_high` | int | `null` | Latest publication year (inclusive) |
| `exclude_domains` | list[string] | `null` | Domains to exclude. Default excludes `researchgate.net`, `books.google.com`, `search.proquest.com`. Pass an empty list `[]` to disable filtering. |

**Example:**
```
GET /search_google_scholar_browser?query=UAV+path+planning&limit=50&year_low=2020
```

**Notes:**
- Requires `browser_worker` to be running and reachable
- If a CAPTCHA appears, open noVNC, solve it once; the session persists for subsequent calls
- `total_records_available` is `null` (Google Scholar does not expose a total count)
- `pdf_link` is populated when Google Scholar provides a direct PDF link; often empty

---

### `GET /search_ieeexplore`

Search IEEE Xplore via the IEEE Xplore Metadata API. Supports Boolean operators and rich filtering. Paginates automatically in pages of 200 (the API maximum) to reach the requested `limit`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | **required** | Search query. Supports `AND`, `OR`, `NOT` Boolean operators |
| `limit` | int ≥ 1 | `25` | Maximum results to return |
| `start_record` | int ≥ 1 | `1` | 1-based offset into the result set (for pagination) |
| `year_low` | int | `null` | Earliest publication year (inclusive) |
| `year_high` | int | `null` | Latest publication year (inclusive) |
| `content_type` | string | `null` | Filter by type: `Books`, `Conferences`, `Courses`, `Early Access`, `Journals`, `Magazines`, `Standards` |
| `open_access` | bool | `null` | `true` = restrict to open-access articles only |
| `sort_field` | string | `null` | One of: `article_number`, `article_title`, `publication_title` |
| `sort_order` | string | `null` | `asc` or `desc` |
| `author` | string (min 3 chars) | `null` | Filter by author first or last name (min 3 characters) |

**Example:**
```
GET /search_ieeexplore?query=UAV+AND+trajectory&limit=50&year_low=2018&content_type=Journals
```

**Pagination example** (get records 201–400):
```
GET /search_ieeexplore?query=UAV+AND+trajectory&limit=200&start_record=201
```

**Notes:**
- Requires `IEEE_XPLORE_API_KEY` environment variable; returns HTTP 400 if missing
- `sort_field` and `sort_order` are validated; invalid values return HTTP 422
- `author` shorter than 3 characters returns HTTP 422 (IEEE API requirement)
- `open_access=false` and omitting `open_access` both return unfiltered results; only `open_access=true` applies a filter
- `pdf_link` points to the IEEE stamp URL when available; full-text access depends on institutional subscription

---

### `GET /search_web_of_science`

Search Web of Science by driving the persistent Chromium browser. Requires an active institutional WoS session.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | **required** | Search query |
| `limit` | int ≥ 1 | `10` | Maximum results to return |
| `year_low` | int | `null` | Earliest publication year (inclusive) |
| `year_high` | int | `null` | Latest publication year (inclusive) |

**Example:**
```
GET /search_web_of_science?query=UAV+trajectory+optimization&limit=20&year_low=2019
```

**Notes:**
- Requires `browser_worker` to be running
- Log in to Web of Science via noVNC before use if the session has expired
- `total_records_available` may be `null` depending on WoS page structure

---

### `GET /search_scopus`

Search Scopus (Elsevier) via the Scopus Search API. Supports full Scopus Boolean query syntax and subject-area filtering. Paginates automatically in pages of 25.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | **required** | Scopus query string. Supports `AND`, `OR`, `NOT`, field codes (`TITLE()`, `ABS()`, `AUTH()`, `TITLE-ABS-KEY()`, etc.) |
| `limit` | int ≥ 1 | `500` | Maximum results to return |
| `start` | int ≥ 0 | `0` | Result offset (0-based) |
| `year_low` | int | `null` | Earliest publication year (inclusive) |
| `year_high` | int | `null` | Latest publication year (inclusive) |
| `subj` | string | `ENGI` | Subject area code. Common codes: `ENGI` (Engineering), `COMP` (Computer Science), `MATE` (Materials Science), `PHYS` (Physics). See [Scopus subject list](https://dev.elsevier.com/documentation/ScopusSearchAPI.wadl) for the full set. |

**Example:**
```
GET /search_scopus?query=TITLE-ABS-KEY(UAV+trajectory)&limit=100&year_low=2018&subj=ENGI
```

**Pagination example** (second page of 25):
```
GET /search_scopus?query=TITLE-ABS-KEY(UAV)&limit=25&start=25
```

**Notes:**
- Requires `ELSEVIER_API_KEY` environment variable
- Default subject filter `ENGI` is always applied unless overridden; set `subj` to a different code as needed

---

### `GET /search_sciencedirect`

Search ScienceDirect (Elsevier) via the Elsevier API. Covers full-text Elsevier journal articles.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | **required** | Free-text search query |
| `limit` | int ≥ 1 | `20` | Maximum results to return |
| `start` | int ≥ 0 | `0` | Result offset (0-based) |
| `year_low` | int | `null` | Earliest publication year (inclusive) |
| `year_high` | int | `null` | Latest publication year (inclusive) |

**Example:**
```
GET /search_sciencedirect?query=UAV+trajectory+optimization&limit=30&year_low=2019
```

**Notes:**
- Requires `ELSEVIER_API_KEY` environment variable
- Complements Scopus: ScienceDirect covers full-text Elsevier articles; Scopus covers abstracts across many publishers

---

### `GET /search_ebsco`

Search EBSCO Research by driving the persistent Chromium browser. Requires an active institutional EBSCO session.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | **required** | Search query |
| `limit` | int ≥ 1 | `100` | Maximum results to return |
| `year_low` | int | `null` | Earliest publication year (inclusive) |
| `year_high` | int | `null` | Latest publication year (inclusive) |

**Example:**
```
GET /search_ebsco?query=UAV+path+planning&limit=50&year_low=2020
```

**Notes:**
- Requires `browser_worker` to be running
- If access is blocked by a login wall, open noVNC, log in through the institution portal, then retry

---

### `GET /download_ebsco_paper`

Download a single paper from an EBSCO detail page URL by navigating the browser.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | string | **required** | EBSCO paper detail page URL (e.g. `https://research.ebsco.com/c/.../search/details/...`) |

**Example:**
```
GET /download_ebsco_paper?url=https://research.ebsco.com/c/abc123/search/details/xyz789
```

**Response:** proxied from `browser_worker` — typically `{ "path": "...", "filename": "...", "size_bytes": ... }` or an error dict.

**Notes:**
- Navigates to the detail page, clicks Download twice (first opens the popup, second confirms), then captures and saves the PDF
- The saved file lands on the `browser_worker` host at its configured download directory

---

### `POST /download_ebsco_papers`

Download multiple EBSCO papers sequentially by their detail page URLs.

**Request body** (JSON array of strings):
```json
[
  "https://research.ebsco.com/c/.../search/details/url1",
  "https://research.ebsco.com/c/.../search/details/url2"
]
```

**Response:** proxied from `browser_worker` — a dict with completed downloads and any failures.

**Notes:**
- Each URL is processed in order; a failure on one URL does not stop the batch
- Timeout scales with the number of URLs: `60s × n + 30s`

---

### `GET /fetch_page`

Fetch and extract readable text content from any URL.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | string | **required** | Page URL to fetch |
| `include_html` | bool | `false` | Include raw HTML in the response |
| `max_chars` | int ≥ 500 | `12000` | Maximum characters of body text to return |

**Example:**
```
GET /fetch_page?url=https://ieeexplore.ieee.org/document/8714567/
```

**Response:**
```json
{
  "url": "https://ieeexplore.ieee.org/document/8714567/",
  "title": "Page title from <title> tag",
  "meta_description": "Meta description content",
  "text": "Extracted body text up to max_chars...",
  "links": ["https://...", "https://...", "...up to 25 hrefs"],
  "html": "<html>...</html>"
}
```

`html` is only present when `include_html=true`.

---

### `GET /review_page`

Like `/fetch_page` but returns additional structure suited for reviewing or summarising a page.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | string | **required** | Page URL to fetch |
| `include_html` | bool | `false` | Include raw HTML in the response |
| `max_chars` | int ≥ 500 | `12000` | Maximum characters of body text to return |

**Example:**
```
GET /review_page?url=https://ieeexplore.ieee.org/document/8714567/
```

**Response:** all fields from `/fetch_page`, plus:
```json
{
  "word_count": 3200,
  "estimated_read_time_minutes": 15,
  "headings": ["Introduction", "Related Work", "Method", "...up to 15 h1/h2/h3 headings"]
}
```

---

### `GET /download_pdf`

Download a PDF directly from a URL and save it to the server's configured download directory.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | string | **required** | Direct URL to a PDF file |

**Example:**
```
GET /download_pdf?url=https://arxiv.org/pdf/2104.02239
```

**Response:**
```json
{
  "path": "/opt/searcher/downloads/2104.02239.pdf",
  "filename": "2104.02239.pdf",
  "size_bytes": 843210
}
```

**Error responses:**
- `400` — URL does not appear to be a PDF (Content-Type mismatch and URL doesn't end in `.pdf`)
- `413` — PDF exceeded the configured max size (default 50 MB)
- `502` — Fetch failed (network error, bad HTTP status)

**Notes:**
- Follows redirects; validates Content-Type header
- Filename derived from the URL path; a short UUID suffix is appended if a file with the same name already exists
- Intended for open-access or pre-authorised direct PDF URLs; does not use the browser session

---

## Common Patterns for AI Agents

### Find papers on a topic

Use `search_ieeexplore` or `search_scopus` for peer-reviewed engineering/CS literature.
Use `search_google_scholar_browser` for broader coverage including preprints and grey literature.
Use `search_semantic_scholar` for quick queries without configuring API keys.

```
# IEEE search with Boolean and filters
GET /search_ieeexplore?query=UAV+AND+trajectory+AND+optimization&limit=50&year_low=2018&content_type=Journals

# Broad Google Scholar search
GET /search_google_scholar_browser?query=UAV+trajectory+optimization&limit=100&year_low=2018

# Scopus with field codes and subject filter
GET /search_scopus?query=TITLE-ABS-KEY(UAV+trajectory)&limit=200&subj=ENGI&year_low=2018
```

### Get details from a result URL

```
GET /fetch_page?url=<result.url>
GET /review_page?url=<result.url>
```

### Download a paper

For open-access PDFs from `result.pdf_link`:
```
GET /download_pdf?url=<result.pdf_link>
```

For subscription papers from IEEE, Elsevier, etc., use the `browser_worker` service (requires institutional session):
```
POST https://searcher.xds-lab.com/aev/browser/download_paper
Content-Type: application/json
{ "url": "<result.url>" }
```

### Paginate results

| Endpoint | Pagination parameter | Style |
|----------|---------------------|-------|
| `search_ieeexplore` | `start_record` | 1-based |
| `search_scopus` | `start` | 0-based |
| `search_sciencedirect` | `start` | 0-based |
| `search_google_scholar_browser` | `start_index` | 0-based |

**IEEE example** — get records 201–400:
```
GET /search_ieeexplore?query=UAV&limit=200&start_record=201
```

**Scopus example** — second page of 25:
```
GET /search_scopus?query=UAV&limit=25&start=25
```

---

## Environment Variables

| Variable | Required by | Description |
|----------|-------------|-------------|
| `IEEE_XPLORE_API_KEY` | `search_ieeexplore` | IEEE Xplore Metadata API key |
| `ELSEVIER_API_KEY` | `search_scopus`, `search_sciencedirect` | Elsevier API key |
| `SEMANTIC_SCHOLAR_API_KEY` | `search_semantic_scholar` | Optional; raises rate limits when set |
| `BROWSER_WORKER_URL` | Browser-backed endpoints | Internal URL of the `browser_worker` service |
| `VNC_PASSWORD` | noVNC access | Password for the noVNC remote desktop |
| `DOWNLOAD_DIR` | `download_pdf` | Server-side directory where PDFs are saved |
| `PDF_MAX_MB` | `download_pdf` | Maximum PDF size in MB (default 50) |

Copy `.env.example` to `.env` (or `.env.dev` for local development) and fill in values before starting services.
