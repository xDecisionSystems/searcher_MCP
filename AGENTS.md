# AGENTS.md

Guidance for programming agents contributing to this repository.

## 1. Mission

Build and maintain a reliable FastAPI service that can:

- Search the web.
- Fetch and review web pages.
- Search scholarly sources.
- Download PDFs safely.

Prioritize correctness, safe defaults, and predictable API behavior.

## 2. Repository Scope

Primary code and runtime files:

- `app.py`: compatibility entrypoint (`uvicorn app:app`).
- `searcher_mcp/`: modular API and business logic (config, services, HTTP helpers).
- `requirements.txt`: Python dependencies.
- `.env.example`: runtime configuration keys.
- `deploy/searcher-mcp.service`: systemd service for Proxmox LXC.
- `README.md`: user-facing setup and usage.

If you add or change behavior in `searcher_mcp/`, update `README.md` and `.env.example` in the same change.

Deployment policy:

- Production deployment is Debian-based Proxmox LXC with `systemd`.
- Local deployment using `.venv` + `uvicorn` is allowed for testing and validation only.
- Use `.env.dev` for local development and local testing runs.
- Do not add additional deployment targets unless explicitly requested.

Deployment and testing permissions:

- Agents may deploy locally for testing only (`.venv` + `uvicorn`).
- Agents must not run production deployment scripts (`./install.sh`, `./update.sh`) as part of normal agent operations.
- Agents are allowed to run testing scripts in `testing/`, including:
  - `./testing/test_health.sh`
  - `./testing/test_smoke.sh`
  - `./testing/test_api_keys.sh`
  - `./testing/test_local_deploy.sh`
- After local test deployment, agents should run verification checks and report results.

## 3. Agent Roles

Use these roles when coordinating multiple programming agents:

- Implementer agent:
  Owns code changes in `app.py` and related modules.
- Documentation agent:
  Owns `README.md`, `ARCHITECTURE.md`, and `CONTRIBUTING.md` updates.
- Verification agent:
  Runs static checks and endpoint smoke tests.

When using multiple agents in parallel, assign disjoint file ownership to avoid merge conflicts.

## 4. Coding Rules

- Use Python 3.10+ compatible syntax.
- Preserve current API contracts unless explicitly asked to break them.
- Keep endpoints deterministic and JSON-serializable.
- Validate all user inputs (URLs, limits, provider names).
- Fail with explicit HTTP status and message.
- Keep network calls bounded with timeouts.
- Never log or expose API keys or secrets.
- Keep external dependencies minimal.
- For standalone scripts, prefer flat top-level execution flow and do not add `main()`.

## 5. Python Environment Rules (Required)

- Always use the repository virtual environment at `.venv`.
- Immediately after creating `.venv`, run `.venv/bin/python -m pip install -r requirements.txt`.
- Re-run `.venv/bin/python -m pip install -r requirements.txt` any time `requirements.txt` changes.
- Prefer explicit executables over relying on shell activation:
  - `.venv/bin/python`
  - `.venv/bin/pip`
- Do not use system/global `python`, `python3`, or `pip` for project tasks.
- For commands in docs, scripts, and examples, prefer:
  - `.venv/bin/python -m pip install -r requirements.txt`
  - `.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000` (local debugging only, not deployment)
- If activation is needed for an interactive session, use:
  - `source .venv/bin/activate`

## 6. Version Update Command Rule

- If the user command is `update version name to <new version name>`, automatically update `VERSION.md`.
- Write the value using this exact format:
  - `VERSION_NAME=<new version name>`
- Do not change key name casing or add extra keys.

## 7. Safety and Security

- Accept only `http`/`https` URLs.
- Treat downloaded content as untrusted.
- Enforce PDF size limits during streaming downloads.
- Reject obviously incorrect content types where possible.
- Do not execute downloaded files.
- Prefer allowlists for provider names and parameters.

## 8. Change Workflow for Agents

1. Read `README.md`, `ARCHITECTURE.md`, and `app.py`.
2. Identify impacted endpoints, config, and docs.
3. Implement smallest coherent change.
4. Run quick checks:
   - `.venv/bin/python -m py_compile app.py searcher_mcp/*.py searcher_mcp/services/*.py`
   - Optional runtime checks if deps are installed.
5. Update docs and examples.
6. Summarize changes, assumptions, and residual risks.

## 9. API Change Policy

Treat these as breaking changes:

- Renaming endpoints.
- Removing response fields.
- Changing default provider behavior.
- Tightening parameter ranges unexpectedly.

If a breaking change is required:

- Add a compatibility path or migration note.
- Update `README.md` and `ARCHITECTURE.md`.
- Call out change impact clearly in PR/task summary.

## 10. Definition of Done

A change is complete when:

- Code is syntactically valid.
- Endpoint behavior matches documentation.
- New config keys are documented in `.env.example`.
- Existing functionality remains intact unless explicitly changed.
- Risks and follow-ups are stated.
