# searcher_MCP

Monorepo containing two independently deployable services intended for separate hosts.

## Services

### [`searcher/`](searcher/)

FastAPI service for scholarly search and web content retrieval.

- Scholar search via Semantic Scholar, Google Scholar (SerpAPI), IEEE Xplore, Web of Science, and Elsevier Scopus
- Web page fetch and review-ready extraction
- Direct PDF download with size and content-type enforcement

Deployed on a Proxmox LXC host. See [searcher/README.md](searcher/README.md).

### [`browser_worker/`](browser_worker/)

FastAPI service that drives a real Chromium browser to download papers from authenticated publisher portals.

- Log in once via a persistent browser session
- Accepts paper page URLs, navigates to the PDF, downloads it to disk
- Intended for pages that require institutional login (e.g. ScienceDirect, IEEE)

Deployed on a separate host with GUI/display access. See [browser_worker/README.md](browser_worker/README.md).

## Repository Layout

```
searcher_MCP/
├── searcher/           # Scholar search FastAPI service
├── browser_worker/     # Browser-automation download FastAPI service
├── exploration/        # Standalone scripts for evaluating integration options
├── CLAUDE.md           # Agent and contributor instructions
└── README.md           # This file
```

## Deployment Overview

All three services run in a single Proxmox LXC (`searcher-stack`, VMID 200 by default).

| Service | Port | Description |
|---------|------|-------------|
| `searcher-mcp` | 8000 | Scholar search FastAPI |
| `browser-worker` | 8010 | Browser-download FastAPI |
| `chromium-cdp` | 9222 (localhost only) | Persistent Chromium CDP instance |

Each service (`searcher/`, `browser_worker/`) has its own `requirements.txt`, `.env.example`, and `deploy/` systemd unit. The deploy script is at `deploy/proxmox_deploy.sh`.
