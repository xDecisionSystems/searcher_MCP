# searcher_MCP

Monorepo containing four services deployed together in a single Proxmox LXC.

## Services

### [`searcher/`](searcher/)

FastAPI service for scholarly search and web content retrieval.

- Scholar search via Semantic Scholar, Google Scholar (SerpAPI), IEEE Xplore, Web of Science, and Elsevier Scopus
- Web page fetch and review-ready extraction
- Direct PDF download with size and content-type enforcement

### [`browser_worker/`](browser_worker/)

FastAPI service that drives a persistent Chromium browser to download papers from authenticated publisher portals.

- Log in once via Chromium CDP — session persists across restarts
- Accepts paper page URLs, navigates to the PDF, downloads it to disk
- Intended for pages that require institutional login (e.g. ScienceDirect, IEEE)

## Repository Layout

```
searcher_MCP/
├── searcher/               # Scholar search FastAPI service
├── browser_worker/         # Browser-automation download FastAPI service
├── deploy/                 # Deployment and operations scripts
│   ├── proxmox_deploy.sh   # Creates LXC and deploys all services
│   ├── update.sh           # Updates code and restarts services in the LXC
│   └── restart.sh          # Restarts all services in dependency order
├── exploration/            # Standalone scripts for evaluating integration options
├── .env.example            # Shared env template covering all services
├── VERSION.md              # Stack version
├── AGENTS.md               # Agent and contributor instructions
├── CLAUDE.md               # Claude Code instructions
└── README.md               # This file
```

## Deployment Overview

All three services run in a single Proxmox LXC.

| Service | Port | Description |
|---------|------|-------------|
| `searcher-mcp` | 8000 | Scholar search FastAPI |
| `browser-worker` | 8010 | Browser-download FastAPI |
| `cdp-gateway` | 8020 | Authenticated CDP login page + WebSocket proxy |
| `chromium-cdp` | 9222 (localhost only) | Persistent Chromium instance |

Deployed code lives at `/opt/repo/` inside the LXC (a git clone of this repo).
A single shared `/opt/repo/.env` covers all services — symlinked from each service directory.

### Quick deploy

```bash
./deploy/proxmox_deploy.sh
```

### Update existing deployment

```bash
pct exec <vmid> -- bash /opt/repo/deploy/update.sh
```

### Restart all services

```bash
pct exec <vmid> -- bash /opt/repo/deploy/restart.sh
```

### Log into publisher portals (ScienceDirect, IEEE, etc.)

1. Open `http://<lxc-ip>:8020/login` — enter your `CDP_LOGIN_KEY` and select a session duration
2. Open Chrome/Edge and go to `chrome://inspect`
3. Click **Configure**, add `<lxc-ip>:8020`
4. Click **inspect** on the remote target and log in to the portal
5. Session is saved to `/opt/repo/browser_worker/chromium-profile` — persists across restarts
6. To revoke access, return to the login page and select **Stop**
