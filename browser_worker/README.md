# browser_worker

FastAPI service that drives a persistent Chromium browser to download papers from authenticated publisher portals. Part of the `searcher-stack` deployment.

## Purpose

- Connect to a co-located `chromium-cdp` Chromium instance via the Chrome DevTools Protocol.
- Navigate to paper pages, resolve PDF links, download and stream to disk.
- Reuse a persistent browser session — log in to publisher portals once, all subsequent requests reuse the session.

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

## Deployment

Deployed as part of the full stack via `deploy/proxmox_deploy.sh` at the repo root. Two systemd services run on the same LXC:

| Service | Description | Port |
|---------|-------------|------|
| `browser-worker` | FastAPI download API | 8010 |
| `chromium-cdp` | Persistent Chromium CDP instance | 9222 |

- Working directory inside LXC: `/opt/repo/browser_worker`
- Env file: `/opt/repo/.env` (shared with all services)
- Chromium profile: `/opt/repo/browser_worker/chromium-profile`

To update a live deployment:
```bash
pct exec <vmid> -- bash /opt/repo/deploy/update.sh
```

## Logging into publisher portals

1. Open Chrome or Edge and go to `chrome://inspect`
2. Click **Configure** and add `<lxc-ip>:9222`
3. Click **inspect** on the remote target
4. Navigate to the publisher portal and log in
5. Session is saved to `/opt/repo/browser_worker/chromium-profile` — persists across restarts

## Local Testing

```bash
cd browser_worker
../.venv/bin/python -m pip install -r requirements.txt
../.venv/bin/python -m playwright install chromium
set -a && source ../.env.dev && set +a
../.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8010
```

Docs: `http://127.0.0.1:8010/docs`

## Environment Variables

All keys are shared via the root `.env.example`.

- `BROWSER_WORKER_CDP_URL` — CDP endpoint (set automatically by deploy script to `http://127.0.0.1:8020`, pointing at `cdp_gateway` which proxies to `chromium-cdp` internally)
- `BROWSER_WORKER_TIMEOUT_SECONDS` (default `45`)
- `BROWSER_WORKER_MAX_DOWNLOAD_MB` (default `100`)
- `BROWSER_WORKER_DOWNLOAD_DIR` (default `/tmp`)
- `BROWSER_WORKER_HEADLESS` — only used when `CDP_URL` is not set (local launch fallback)
- `BROWSER_WORKER_SESSION_DIR` — only used when `CDP_URL` is not set (local launch fallback)
- `BROWSER_WORKER_USER_AGENT`
