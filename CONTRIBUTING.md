# CONTRIBUTING.md

Thanks for contributing to Searcher MCP.

## 1. Prerequisites

- Python 3.10+
- `venv` support
- Network access for provider APIs during runtime testing

## 2. Local Setup

```bash
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env.dev
set -a && source .env.dev && set +a
```

Add API keys in `.env.dev` as needed.

## 3. Development Workflow

1. Create a focused branch.
2. Make a small, coherent change.
3. Run checks.
4. Update docs if behavior/config changed.
5. Open a PR with clear notes.

## 4. Validation Checklist

Minimum required before merge:

- `.venv/bin/python -m py_compile app.py searcher_mcp/*.py searcher_mcp/services/*.py`
- Confirm `/health` responds.
- Confirm changed endpoints return expected JSON shape.
- Confirm failures return reasonable HTTP codes/messages.
- Confirm README examples still work or are updated.

Recommended smoke checks:

```bash
curl "http://127.0.0.1:8000/health"
curl "http://127.0.0.1:8000/search_scholar?query=test&provider=semantic_scholar"
curl "http://127.0.0.1:8000/fetch_page?url=https://example.com"
curl "http://127.0.0.1:8000/review_page?url=https://example.com"
```

## 5. Code Style

- Follow existing style in `app.py` and service modules.
- Keep functions short and purpose-specific.
- Prefer explicit error handling over silent fallback.
- Use type hints for new/changed functions.
- Avoid adding dependencies unless necessary.

## 6. Documentation Requirements

Update these files when relevant:

- `README.md`: setup, endpoints, usage examples
- `.env.example`: new environment variables
- `ARCHITECTURE.md`: structural or data-flow changes
- `AGENTS.md`: agent workflow/policy changes

## 7. Security and Privacy

- Never commit real API keys.
- Do not print secrets to logs or responses.
- Validate URLs and enforce request timeouts.
- Keep file download logic bounded by size and type checks.

## 8. Pull Request Template

Include:

- What changed.
- Why it changed.
- How you validated it.
- Any breaking changes or migration notes.
- Any follow-up tasks.
