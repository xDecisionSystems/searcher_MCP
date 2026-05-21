# CLAUDE.md

Repository instructions for Claude-based programming agents.

## Repository Structure

This is a monorepo with four services deployed together in a single Proxmox LXC:

- `searcher/` — FastAPI scholarly search and web content service (port 8000)
- `browser_worker/` — FastAPI Playwright browser-automation download service (port 8010)
- `chromium-cdp` — Persistent Chromium instance managed by `browser_worker/deploy/chromium-cdp.service` (port 9222)

Each service has its own `requirements.txt` and `deploy/` folder. There is a single shared `.env.example` and `VERSION.md` at the repo root.

## Deployment Policy

- Production deployment is a single Debian-based Proxmox LXC with `systemd`.
- All services deploy to `/opt/repo/` inside the LXC (git clone of this repo).
- Shared env lives at `/opt/repo/.env`; each service symlinks to it.
- Local deployment using `.venv` + `uvicorn` is allowed for testing and validation only.
- Use `.env.dev` at the repo root for local development.
- Do not add additional deployment targets unless explicitly requested.

## Deployment and Testing Permissions

- Claude may deploy locally for testing only (`.venv` + `uvicorn`).
- Claude must not run `deploy/proxmox_deploy.sh` or per-service `install.sh`/`update.sh` (legacy, unused).
- Claude may run `deploy/update.sh` inside the LXC to update a live deployment when explicitly asked.
- Claude is allowed to run testing scripts in each service's `testing/` folder.
- After local test deployment, Claude should run verification checks and report results.

## 1. Environment Requirement (Mandatory)

- A single `.venv` is shared at the repo root for local development.
- Install a service's deps with: `.venv/bin/python -m pip install -r <service>/requirements.txt`
- Re-run whenever a service's `requirements.txt` changes.
- Do not use global/system Python or pip for project work.
- Prefer explicit commands:
  - `.venv/bin/python`
  - `.venv/bin/pip`

## 2. Standard Command Patterns

- Install searcher deps: `.venv/bin/python -m pip install -r searcher/requirements.txt`
- Install browser_worker deps: `.venv/bin/python -m pip install -r browser_worker/requirements.txt`
- Run searcher locally: `cd searcher && ../.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000`
- Run browser_worker locally: `cd browser_worker && ../.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8010`
- Syntax check searcher: `.venv/bin/python -m py_compile searcher/app.py searcher/searcher_mcp/*.py searcher/searcher_mcp/services/*.py`
- Syntax check browser_worker: `.venv/bin/python -m py_compile browser_worker/app.py browser_worker/browser_worker/*.py browser_worker/browser_worker/services/*.py`
- Syntax check cdp_gateway: `.venv/bin/python -m py_compile cdp_gateway/app.py cdp_gateway/cdp_gateway/*.py`
- Run cdp_gateway locally: `cd cdp_gateway && ../.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8020`
- For standalone scripts, prefer flat top-level execution flow and do not add `main()`.

## 3. Version Update Command Rule

- If the user says `update version name to <new version name>`, update `VERSION.md` at the repo root.
- Use exactly: `VERSION_NAME=<new version name>`
- Keep the key name exactly `VERSION_NAME`.

## 4. Change Hygiene

- When code changes affect behavior, update docs in the same change.
- Keep API responses stable unless a breaking change is explicitly requested.
- Validate all input and return clear HTTP errors.

## 5. Security Basics

- Never expose API keys or secrets.
- Treat downloaded content as untrusted.
- Keep request timeouts and PDF size limits enforced.
- `browser_worker/` can access arbitrary URLs — keep it on a trusted network segment.
