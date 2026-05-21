# AGENTS.md

Guidance for programming agents contributing to this repository.

## 1. Mission

Maintain two reliable FastAPI services:

- `searcher/` — scholarly search, web page retrieval, and PDF download via HTTP APIs.
- `browser_worker/` — browser-driven paper download for authenticated publisher portals.

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
│   ├── .env.example
│   ├── deploy/searcher-mcp.service
│   ├── testing/
│   └── VERSION.md
├── browser_worker/                  # Browser-automation download service
│   ├── app.py
│   ├── browser_worker/
│   │   ├── api.py
│   │   ├── config.py
│   │   └── services/download.py
│   ├── requirements.txt
│   ├── .env.example
│   ├── deploy/browser-worker.service
│   └── VERSION.md
├── exploration/                     # Standalone evaluation scripts (not production)
├── AGENTS.md
├── CLAUDE.md
└── README.md
```

If you add or change behavior in a service, update that service's `README.md` and `.env.example` in the same change.

## 3. Deployment Policy

- Production: Debian-based Proxmox LXC with `systemd`.
- `searcher/` and `browser_worker/` are deployed on **separate LXC hosts**.
- Local `.venv` + `uvicorn` is for testing only.
- Do not run `install.sh` or `update.sh` as part of normal agent operations.

## 4. Agent Roles

- **Implementer agent**: owns code changes inside a service's module (`searcher_mcp/` or `browser_worker/`).
- **Documentation agent**: owns `README.md`, `ARCHITECTURE.md` (where present), `.env.example`.
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

- `update version name to <new>` → update `VERSION.md` in the relevant service folder.
- Format: `VERSION_NAME=<new version name>`

## 8. Safety and Security

- Accept only `http`/`https` URLs.
- Treat downloaded content as untrusted.
- Enforce PDF size limits during streaming downloads.
- Reject obviously incorrect content types where possible.
- Do not execute downloaded files.
- `browser_worker/` can navigate arbitrary URLs — never expose it publicly without auth.

## 9. Change Workflow

1. Identify which service is affected (`searcher/` or `browser_worker/`).
2. Read that service's `README.md` and main module files.
3. Implement the smallest coherent change.
4. Run syntax checks for the affected service.
5. Update that service's docs and `.env.example`.
6. Summarize changes, assumptions, and residual risks.

## 10. Definition of Done

- Code is syntactically valid.
- Endpoint behavior matches documentation.
- New config keys are documented in the service's `.env.example`.
- Existing functionality remains intact unless explicitly changed.
- Risks and follow-ups are stated.
