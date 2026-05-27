# browser_worker

FastAPI service that drives a persistent Chromium browser to download papers from authenticated publisher portals. Part of the `searcher-stack` deployment.

## Purpose

- Connect to a co-located Chromium instance via the Chrome DevTools Protocol (CDP).
- Navigate to paper pages using per-domain strategy files, resolve the PDF, and download it to disk.
- Reuse a persistent browser session — log in to publisher portals once via noVNC, all subsequent requests reuse the session.
- Serialize downloads: only one download runs at a time. Returns `status=busy` immediately if a download is already in progress.

## Endpoints

### Download

- `POST /download_paper` — download a single paper by URL
- `POST /download_papers` — download a list of URLs sequentially

`POST /download_paper` request body:

```json
{
  "url": "https://example.com/paper-page",
  "filename": "optional-output-name.pdf"
}
```

On success the response does **not** contain a `status` field. Instead it contains:

| Field | Description |
|-------|-------------|
| `path` | Absolute path to the saved PDF on disk |
| `filename` | Filename of the saved PDF |
| `size_bytes` | Size of the downloaded PDF in bytes |
| `source_url` | Final URL from which the PDF was fetched |
| `method` | Strategy step or method used to download the file |

On failure the response contains a `status` field:

| Status | Meaning |
|--------|---------|
| `login_required` | Login or CAPTCHA detected; `user_prompt` explains what to do; retry same call after resolving |
| `busy` | Another download is in progress; retry after it finishes |
| `no_access` | Institutional access does not cover this specific paper (paywall); `message` explains |
| `inaccessible` | Institution does not have access to this publisher at all; `message` explains |
| `failed` | Download attempt did not produce a PDF |

`POST /download_papers` request body:

```json
{
  "urls": ["https://example.com/paper1", "https://example.com/paper2"],
  "stop_on_login": true
}
```

When `stop_on_login=true` (default), the queue pauses on `login_required` or `busy` and returns `paused_at` plus `pending` so the caller can retry the remainder after resolving the issue.

### Browser and Scholar

- `GET /search_google_scholar` — search Google Scholar using the real Chromium browser
- `GET /fetch_page` — navigate to a URL and return its rendered HTML

### Recording

Use these to teach the service how to download from a new domain.

- `POST /record_session?url=<paper-url>&timeout_seconds=60` — start recording a browser session
- `POST /stop_recording` — stop the active recording and save the strategy
- `GET /recording_status` — check recording state (`idle` / `recording` / `saved` / `error`)

### Strategy Management

Per-domain strategy files live in `browser_worker/strategies/`.

- `GET /strategies` — list all saved strategies
- `GET /strategies/{domain}` — get strategy for a domain (404 if not found)
- `PUT /strategies/{domain}` — write or replace a strategy
- `DELETE /strategies/{domain}` — delete a strategy

Domain matching uses a suffix fallback: `theses.hal.science` → `hal.science`. This means one strategy covers all `*.hal.science` subdomains unless a more-specific file exists (e.g. `enac.hal.science.json`).

### Files and Diagnostics

- `GET /files` — list downloaded files
- `GET /files/{filename}` — download a file by name
- `GET /logs?n=50` — return last `n` structured log events (navigation, selectors tried, failures)
- `GET /health` — liveness check

## Strategy Files

Each domain strategy is a JSON file at `browser_worker/strategies/<domain>.json`. Key fields:

| Field | Description |
|-------|-------------|
| `domain` | The domain this strategy covers |
| `accessible` | `false` if the institution has no access to this publisher |
| `inaccessible_reason` | Human-readable explanation when `accessible=false` |
| `login_detection` | Signals and auth domain patterns for detecting login walls |
| `no_access_signals` | Phrases in page HTML that indicate per-paper paywall |
| `post_process` | Post-download operations (e.g. `strip_first_pages: 1` for HAL coversheets) |
| `steps` | Ordered list of browser actions (`click`, `wait_for_pdf_response`) |

Currently supported domains:

- `apps.dtic.mil` — Defense Technical Information Center
- `arc.aiaa.org` — AIAA Arc
- `arxiv.org` — arXiv
- `dl.acm.org` — ACM Digital Library
- `dspace.mit.edu` — MIT DSpace
- `enac.hal.science` — ENAC HAL (French interface)
- `hal.science` — HAL Open Science (covers all `*.hal.science` subdomains via suffix fallback)
- `icas.org` — International Council of the Aeronautical Sciences
- `ieeexplore.ieee.org` — IEEE Xplore
- `journals.sagepub.com` — SAGE Journals (Cloudflare CAPTCHA — solve once via noVNC)
- `link.springer.com` — Springer Link
- `ntrs.nasa.gov` — NASA Technical Reports Server
- `pubsonline.informs.org` — INFORMS PubsOnLine
- `rosap.ntl.bts.gov` — ROSAP (Bureau of Transportation Statistics)
- `www.academia.edu` — Academia.edu
- `www.cambridge.org` — Cambridge University Press (inaccessible — no institutional access)
- `www.frontiersin.org` — Frontiers
- `www.mdpi.com` — MDPI
- `www.nature.com` — Nature
- `www.researchgate.net` — ResearchGate (Cloudflare CAPTCHA — solve once via noVNC)
- `www.sciencedirect.com` — ScienceDirect (Elsevier)
- `www.sciopen.com` — SciOpen
- `www.tandfonline.com` — Taylor & Francis Online

## Deployment

| Service | Description | Port |
|---------|-------------|------|
| `browser-worker` | FastAPI download API | 8010 |
| `chromium-cdp` | Persistent Chromium CDP instance | 9222 (localhost) |

- Working directory inside LXC: `/opt/searcher/browser_worker`
- Env file: `/opt/searcher/.env` (shared with all services)
- Chromium profile: `/opt/searcher/browser_worker/chromium-profile`

To update a live deployment:
```bash
pct exec <vmid> -- bash /opt/searcher/deploy/update.sh
```

## Logging into publisher portals

1. Open `https://searcher.xds-lab.com/aev/novnc/vnc.html` in your browser
2. Enter your `VNC_PASSWORD`
3. A full Chromium browser appears — log in to the portal normally
4. Session is saved to `/opt/searcher/browser_worker/chromium-profile` — persists across restarts

## Local Testing

```bash
cd browser_worker
../.venv/bin/python -m pip install -r requirements.txt
set -a && source ../.env.dev && set +a
../.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8010
```

Docs: `http://127.0.0.1:8010/docs`

Syntax check:
```bash
../.venv/bin/python -m py_compile app.py browser_worker/*.py browser_worker/services/*.py
```

## Environment Variables

All keys are shared via the root `.env.example`.

- `BROWSER_WORKER_CDP_URL` — CDP endpoint for the Chromium instance (e.g. `http://127.0.0.1:9222`)
- `BROWSER_WORKER_TIMEOUT_SECONDS` (default `45`)
- `BROWSER_WORKER_MAX_DOWNLOAD_MB` (default `100`)
- `BROWSER_WORKER_DOWNLOAD_DIR` (default `/tmp`)
- `BROWSER_WORKER_USER_AGENT`
