---
name: project-architecture
description: Current architecture of the searcher stack — two services plus browser stack in one Proxmox LXC
metadata:
  type: project
---

Two FastAPI services and a browser stack deploy to a single Proxmox LXC (`searcher-stack`) via `deploy/proxmox_deploy.sh`. Code lives at `/opt/searcher/` inside the LXC. A single `/opt/searcher/.env` is shared by all services via symlinks.

| Service | Port | Description |
|---------|------|-------------|
| `searcher-mcp` | 8000 | Scholar search FastAPI |
| `browser-worker` | 8010 | Playwright browser download FastAPI |
| `chromium-display` | 9222 (localhost only) | Persistent Chromium with GUI on Xvfb :99 |
| `x11vnc` | 5900 (localhost) | VNC server |
| `novnc` | 6080 | Browser-based VNC client |

**Why:** Both APIs are open (no auth). Browser access for login is via noVNC.

**How to apply:** Do not add auth to searcher or browser_worker. Restrict port 9222 by firewall if needed.
