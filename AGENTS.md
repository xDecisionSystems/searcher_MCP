# AGENTS.md

Guidance for programming agents contributing to this repository.

## 1. Mission

Maintain three FastAPI services and one Chromium process deployed together as a single stack:

- `searcher/` — scholarly search, web page retrieval, and PDF download via HTTP APIs.
- `browser_worker/` — browser-driven paper download for authenticated publisher portals.
- `cdp_gateway/` — JWT-authenticated login page and WebSocket proxy for Chromium CDP access.

Prioritize correctness, safe defaults, and predictable API behavior.

## 2. Repository Scope

```
searcher_MCP/
├── searcher/                        # Search API service
│   ├── app.py                       # Entrypoint
│   ├── searcher_mcp/                # API routes and business logic
│   │   ├── api.py
│   │   ├── config.py
│   │   ├── http_client.py
│   │   ├── utils.py
│   │   └── services/
│   │       ├── page.py
│   │       ├── pdf.py
│   │       └── search.py
│   ├── requirements.txt
│   ├── deploy/searcher-mcp.service
│   ├── testing/
│   ├── README.md
│   └── ARCHITECTURE.md
├── browser_worker/                  # Browser-automation download service
│   ├── app.py
│   ├── browser_worker/
│   │   ├── api.py
│   │   ├── config.py
│   │   └── services/download.py
│   ├── requirements.txt
│   ├── deploy/
│   │   ├── browser-worker.service
│   │   └── chromium-cdp.service
│   └── README.md
├── cdp_gateway/                     # Authenticated CDP login page + WebSocket proxy
│   ├── app.py
│   ├── cdp_gateway/
│   │   ├── api.py
│   │   ├── config.py
│   │   ├── session.py
│   │   └── templates/login.html
│   ├── requirements.txt
│   └── deploy/cdp-gateway.service
├── deploy/                          # Stack-level deployment scripts
│   ├── proxmox_deploy.sh            # Creates LXC and deploys all services
│   ├── update.sh                    # Updates code and restarts in the LXC
│   └── restart.sh                   # Restarts all services in dependency order
├── exploration/                     # Standalone evaluation scripts (not production)
├── .env.example                     # Shared env template for all services
├── VERSION.md                       # Stack version (single file at repo root)
├── AGENTS.md
├── CLAUDE.md
└── README.md
```

If you add or change behavior in a service, update that service's `README.md` and the root `.env.example` in the same change.

## 3. Deployment Policy

- Production: single Debian-based Proxmox LXC with `systemd`, running four services.
- Code is deployed to `/opt/repo/` inside the LXC (git clone of this repo).
- Shared env lives at `/opt/repo/.env`; each service symlinks to it.
- Local `.venv` + `uvicorn` is for testing only.
- Use `deploy/update.sh` inside the LXC for code updates — no full redeploy needed.
- Do not run per-service `install.sh` or `update.sh` — these are legacy and unused.

## 4. Agent Roles

- **Implementer agent**: owns code changes inside a service's module (`searcher_mcp/` or `browser_worker/`).
- **Documentation agent**: owns `README.md`, `ARCHITECTURE.md`, root `.env.example`.
- **Verification agent**: runs syntax checks and smoke tests for the affected service.

When using multiple agents in parallel, assign disjoint file ownership.

## 5. Coding Rules

- Python 3.10+ compatible syntax.
- Preserve current API contracts unless explicitly asked to break them.
- Keep endpoints deterministic and JSON-serializable.
- Validate all user inputs (URLs, limits, provider names).
- Fail with explicit HTTP status and message.
- Keep network calls bounded with timeouts.
- Never log or expose API keys or secrets.
- Keep external dependencies minimal.
- For standalone scripts, prefer flat top-level execution flow and do not add `main()`.

## 6. Python Environment Rules (Required)

- Shared `.venv` at repo root for local development.
- Install service deps: `.venv/bin/python -m pip install -r <service>/requirements.txt`
- Re-run whenever a service's `requirements.txt` changes.
- Do not use system/global `python`, `python3`, or `pip` for project tasks.

## 7. Version Update Command Rule

- `update version name to <new>` → update `VERSION.md` at the **repo root**.
- Format: `VERSION_NAME=<new version name>`

## 8. Safety and Security

- Accept only `http`/`https` URLs.
- Treat downloaded content as untrusted.
- Enforce PDF size limits during streaming downloads.
- Reject obviously incorrect content types where possible.
- Do not execute downloaded files.
- `browser_worker/` can navigate arbitrary URLs — restrict port 9222 by firewall if needed.

## 9. Change Workflow

1. Identify which service is affected (`searcher/` or `browser_worker/`).
2. Read that service's `README.md` and main module files.
3. Implement the smallest coherent change.
4. Run syntax checks for the affected service.
5. Update that service's docs and the root `.env.example` if config keys changed.
6. Summarize changes, assumptions, and residual risks.

## 10. Definition of Done

- Code is syntactically valid.
- Endpoint behavior matches documentation.
- New config keys are documented in the root `.env.example`.
- Existing functionality remains intact unless explicitly changed.
- Risks and follow-ups are stated.
