---
name: project-architecture
description: Current architecture of the searcher_MCP stack — four services in one Proxmox LXC
metadata:
  type: project
---

All four services deploy to a single Proxmox LXC (`searcher-stack`) via `deploy/proxmox_deploy.sh`. Code lives at `/opt/repo/` inside the LXC. A single `/opt/repo/.env` is shared by all services via symlinks.

| Service | Port | Description |
|---------|------|-------------|
| `searcher-mcp` | 8000 | Scholar search FastAPI — open, no auth |
| `browser-worker` | 8010 | Playwright browser download FastAPI — open, no auth |
| `cdp-gateway` | 8020 | JWT-gated login page + CDP WebSocket proxy |
| `chromium-cdp` | 9222 (localhost only) | Persistent Chromium instance |

**Why:** searcher and browser_worker are open APIs. JWT is only required to access Chromium DevTools via cdp_gateway.

**How to apply:** Do not add auth to searcher or browser_worker. JWT gating lives exclusively in cdp_gateway.

**CDP Gateway flow:**
1. User visits `http://<lxc-ip>:8020/login`, enters `CDP_LOGIN_KEY`, selects duration
2. JWT issued, embedded into `/json` WebSocket URLs automatically
3. `chrome://inspect` connects to port 8020 — token travels in WS query string
4. `browser_worker` also connects to cdp_gateway (port 8020) not directly to chromium-cdp (9222)

**Key env vars:** `CDP_LOGIN_KEY`, `CDP_JWT_SECRET`, `CDP_GATEWAY_PORT=8020`
