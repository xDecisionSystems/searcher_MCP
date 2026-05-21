# Browser Worker (FastAPI)

Dedicated browser-automation worker service intended to run on a separate host from the main Searcher API.

## Purpose

- Open target pages with a real Chromium browser context.
- Resolve PDF content either directly from page response or discovered PDF links.
- Download papers to local disk and return metadata.

In production this service runs alongside a `chromium-cdp` systemd service on the same host. Chromium runs persistently with a saved profile so you can log into publisher portals (ScienceDirect, IEEE, etc.) once and reuse the session for all subsequent downloads.

## Endpoints

- `GET /health`
- `POST /download_paper`

`POST /download_paper` body:

```json
{
  "url": "https://example.com/paper-page",
  "filename": "optional-output-name.pdf"
}
```

## Local Run

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
cp .env.example .env
set -a && source .env && set +a
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8010
```

Docs:

- `http://127.0.0.1:8010/docs`

## Deployment Notes

- Intended to be deployed on a separate host from `searcher/`.
- Keep this service on a trusted network segment; it can access arbitrary URLs.
- Use host-level controls (firewall, reverse proxy auth, VPN) before exposing externally.

## Services on the Same Host

The deploy script installs two systemd services on this LXC:

| Service | Description | Port |
|---------|-------------|------|
| `browser-worker` | FastAPI download API | 8010 |
| `chromium-cdp` | Persistent Chromium CDP instance | 9222 (localhost only) |

`browser-worker` connects to `chromium-cdp` via `BROWSER_WORKER_CDP_URL=http://127.0.0.1:9222`.

### Logging into publisher portals

To authenticate with ScienceDirect, IEEE, or other portals:

1. SSH port-forward the CDP port to your local machine:
   ```bash
   ssh -L 9222:127.0.0.1:9222 root@<lxc-ip>
   ```
2. Open Chrome or Edge and go to `chrome://inspect`
3. Click **Configure** and add `localhost:9222`
4. Click **inspect** on the remote target — a DevTools window opens showing the Chromium instance running on the LXC
5. Navigate to the publisher portal and log in
6. Close DevTools — the session is saved to `/opt/browser_worker/chromium-profile` and persists across restarts

## Environment Variables

- `BROWSER_WORKER_CDP_URL` — URL of the Chromium CDP endpoint (default: `http://127.0.0.1:9222`)
- `BROWSER_WORKER_TIMEOUT_SECONDS`
- `BROWSER_WORKER_MAX_DOWNLOAD_MB`
- `BROWSER_WORKER_DOWNLOAD_DIR`
- `BROWSER_WORKER_HEADLESS` — only used when CDP_URL is not set (local launch fallback)
- `BROWSER_WORKER_SESSION_DIR` — only used when CDP_URL is not set (local launch fallback)
- `BROWSER_WORKER_USER_AGENT`
