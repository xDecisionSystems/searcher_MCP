# CLAUDE.md

Repository instructions for Claude-based programming agents.

Deployment policy:

- Production deployment is Debian-based Proxmox LXC with `systemd`.
- Local deployment using `.venv` + `uvicorn` is allowed for testing and validation only.
- Use `.env.dev` for local development and local testing runs.
- Do not add additional deployment targets unless explicitly requested.

Deployment and testing permissions:

- Claude may deploy locally for testing only (`.venv` + `uvicorn`).
- Claude must not run production deployment scripts (`./install.sh`, `./update.sh`) as part of normal agent operations.
- Claude is allowed to run testing scripts in `testing/`, including:
  - `./testing/test_health.sh`
  - `./testing/test_smoke.sh`
  - `./testing/test_api_keys.sh`
  - `./testing/test_local_deploy.sh`
- After local test deployment, Claude should run verification checks and report results.

## 1. Environment Requirement (Mandatory)

- Use the repository virtual environment located at `.venv`.
- Immediately after creating `.venv`, run `.venv/bin/python -m pip install -r requirements.txt`.
- Re-run `.venv/bin/python -m pip install -r requirements.txt` any time `requirements.txt` changes.
- Do not use global/system Python or pip for project work.
- Prefer explicit commands:
  - `.venv/bin/python`
  - `.venv/bin/pip`

## 2. Standard Command Patterns

- Install dependencies:
  - `.venv/bin/python -m pip install -r requirements.txt`
- Run API:
  - `.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000` (local debugging only, not deployment)
- Run syntax checks:
  - `.venv/bin/python -m py_compile app.py searcher_mcp/*.py searcher_mcp/services/*.py`
- For standalone scripts, prefer flat top-level execution flow and do not add `main()`.

If an interactive shell needs activation, use:

- `source .venv/bin/activate`

## 3. Version Update Command Rule

- If the user says `update version name to <new version name>`, automatically update `VERSION.md`.
- Use exactly:
  - `VERSION_NAME=<new version name>`
- Keep the key name exactly `VERSION_NAME`.

## 4. Change Hygiene

- When code changes affect behavior, update docs in the same change.
- Keep API responses stable unless a breaking change is explicitly requested.
- Validate all input and return clear HTTP errors.

## 5. Security Basics

- Never expose API keys or secrets.
- Treat downloaded content as untrusted.
- Keep request timeouts and PDF size limits enforced.
