# ARCHITECTURE.md

Architecture overview for the Searcher MCP FastAPI service.

## 1. High-Level Design

This project is a single-service HTTP API built with FastAPI.

Core responsibilities:

- Web search via pluggable providers.
- Web page retrieval and content extraction for review.
- Scholarly paper search.
- PDF download with safety limits.

The current implementation is monolithic in `app.py` for simplicity.

## 2. Runtime Components

- FastAPI app object:
  Defines HTTP routes and OpenAPI docs.
- Shared `requests.Session`:
  Reused for outbound HTTP calls with a configured User-Agent.
- Provider adapters:
  Internal functions that normalize upstream results into project JSON shapes.
- Extraction/parsing layer:
  Uses BeautifulSoup for HTML cleanup and content extraction.
- Download manager:
  Streams PDF bytes to disk with size checks.

## 3. Request Flow

Generic request lifecycle:

1. FastAPI route receives and validates query parameters.
2. Route selects helper function(s).
3. Helper performs outbound HTTP request(s) with timeout.
4. Response data is normalized into deterministic JSON.
5. Errors map to HTTPException with explicit status and message.

## 4. Endpoint Map

- `/health`:
  Lightweight liveness endpoint.
- `/search_web`:
  Provider-agnostic web search with `provider=auto` fallback chain.
- `/search_google`:
  Explicit SerpAPI-backed Google search.
- `/fetch_page`:
  Retrieves HTML and returns extracted textual content.
- `/review_page`:
  Extends fetch output with headings and readability metrics.
- `/search_scholar`:
  Scholar search through Semantic Scholar or SerpAPI Google Scholar.
- `/search_google_scholar`:
  Explicit SerpAPI-backed Google Scholar search.
- `/download_pdf`:
  Streams PDF to disk with content-type and max-size enforcement.

## 5. Provider Selection Logic

Web search provider selection in `/search_web` when `provider=auto`:

1. SerpAPI Google (if `SERPAPI_API_KEY`)
2. Brave Search (if `BRAVE_SEARCH_API_KEY`)
3. Bing Search (if `BING_SEARCH_API_KEY`)
4. DuckDuckGo HTML fallback

Scholar provider selection in `/search_scholar` when `provider=auto`:

1. Semantic Scholar

## 6. Configuration Model

Configuration is environment-driven:

- `SERPAPI_API_KEY`
- `BRAVE_SEARCH_API_KEY`
- `BING_SEARCH_API_KEY`
- `SEMANTIC_SCHOLAR_API_KEY`
- `REQUEST_TIMEOUT_SECONDS`
- `PDF_MAX_MB`
- `DOWNLOAD_DIR`
- `MCP_USER_AGENT`

`.env.example` documents expected variables.

## 7. Data Contracts

Design goals for response schemas:

- Stable top-level keys.
- Predictable list/object shapes.
- Provider metadata included in search responses.
- Human-readable error details.

When changing response schemas, update `README.md` and announce impact.

## 8. Deployment Topology

Primary production environment is Debian-based Proxmox LXC with systemd management.
Local `.venv` + `uvicorn` deployment is also supported for testing only.

- Service file: `deploy/searcher-mcp.service`
- Working directory: `/opt/searcher_mcp`
- Process manager: `systemd`
- App server: `uvicorn`

## 9. Security Considerations

- URL scheme validation prevents non-web schemes.
- Outbound requests use explicit timeouts.
- PDF downloads are streamed and size-bounded.
- Untrusted HTML is parsed, not executed.
- Secrets are expected in environment variables, not source control.

## 10. Recommended Future Refactors

- Split `app.py` into modules:
  `routers/`, `providers/`, `schemas/`, `services/`.
- Add Pydantic response models for stronger contracts.
- Add test suite for endpoint behavior and provider normalization.
- Add structured logging and request IDs.
