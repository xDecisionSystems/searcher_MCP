# searcher_MCP

Monorepo containing two FastAPI services and a browser stack deployed together in a single Proxmox LXC.

## Services

### [`searcher/`](searcher/)

FastAPI service for scholarly search and web content retrieval.

- Scholar search via Semantic Scholar, Google Scholar (scholarly library + browser fallback), IEEE Xplore, Web of Science, and Elsevier Scopus
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
searcher_MCP/
├── searcher/                    # Scholar search FastAPI service
├── browser_worker/              # Browser-automation download FastAPI service
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

### Using as MCP servers with Claude Code

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

Available MCP tools for `searcher`: `search_scholar`, `search_google_scholar`, `search_google_scholar_browser`, `search_ieeexplore`, `search_web_of_science`, `search_scopus`, `fetch_page`, `review_page`, `download_pdf`.

Available MCP tools for `browser_worker`: `download_paper`, `download_papers`, `fetch_page`, `search_google_scholar`, `record_session`, `stop_recording`, `recording_status`, `list_strategies`, `get_strategy`, `put_strategy`, `delete_strategy`, `list_files`, `get_file`, `get_logs`.

### Update existing deployment

```bash
pct exec <vmid> -- bash /opt/searcher/deploy/update.sh
```

### Restart all services

```bash
pct exec <vmid> -- bash /opt/searcher/deploy/restart.sh
```

### Log into publisher portals (ScienceDirect, IEEE, etc.)

1. Open `https://searcher.xds-lab.com/aev/novnc/vnc.html` in your browser
2. Enter your `VNC_PASSWORD`
3. A full Chromium browser appears — log in to the portal normally
4. Session is saved to `/opt/searcher/browser_worker/chromium-profile` — persists across restarts
