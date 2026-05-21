# ARCHITECTURE.md

Architecture overview for the Searcher MCP FastAPI service.

## 1. High-Level Design

This project is a single-service HTTP API built with FastAPI.

Core responsibilities:

- Scholar search via pluggable scholarly providers.
- Web page retrieval and content extraction for review.
- PDF download with safety limits.

The implementation is modular:

- `app.py` is a thin compatibility entrypoint.
- `searcher_mcp/api.py` defines FastAPI routes.
- `searcher_mcp/services/` contains business logic by domain.
- `searcher_mcp/config.py` centralizes environment-driven settings.
- `searcher_mcp/http_client.py` owns shared HTTP session/request helpers.

## 2. Runtime Components

- FastAPI app object:
  Defines HTTP routes and OpenAPI docs.
- Shared `requests.Session`:
  Reused for outbound HTTP calls with a configured User-Agent.
- Provider adapters:
  Internal functions that normalize upstream scholarly results into project JSON shapes.
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
- `/search_scholar`:
  Unified scholarly search router for Semantic Scholar, SerpAPI Google Scholar, IEEE Xplore, Web of Science, and Scopus.
- `/search_google_scholar`:
  Explicit SerpAPI-backed Google Scholar search.
- `/search_ieeexplore`:
  IEEE Xplore metadata search using API key authentication.
- `/search_web_of_science`:
  Clarivate Web of Science Starter API search using API key authentication.
- `/search_scopus`:
  Elsevier Scopus Search API using API key authentication.
- `/fetch_page`:
  Retrieves HTML and returns extracted textual content.
- `/review_page`:
  Extends fetch output with headings and readability metrics.
- `/download_pdf`:
  Streams PDF to disk with content-type and max-size enforcement.

## 5. Provider Selection Logic

Scholar provider selection in `/search_scholar` when `provider=auto`:

1. Semantic Scholar

Explicit provider names supported by `/search_scholar`:

- `semantic_scholar`
- `google_scholar_serpapi`
- `ieeexplore`
- `web_of_science`
- `scopus`

## 6. Configuration Model

Configuration is environment-driven:

- `SERPAPI_API_KEY`
- `IEEE_XPLORE_API_KEY`
- `SEMANTIC_SCHOLAR_API_KEY`
- `WEB_OF_SCIENCE_API_KEY`
- `ELSEVIER_API_KEY`
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
- Working directory: `/opt/searcher`
- Process manager: `systemd`
- App server: `uvicorn`

## 9. Security Considerations

- URL scheme validation prevents non-web schemes.
- Outbound requests use explicit timeouts.
- PDF downloads are streamed and size-bounded.
- Untrusted HTML is parsed, not executed.
- Secrets are expected in environment variables, not source control.

## 10. Exploration Directory

`../exploration/` (repository root) contains standalone scripts used to test, explore, and evaluate options being considered for integration into the app. Scripts there are not part of the production codebase, may have additional dependencies beyond `requirements.txt`, and are not subject to the standard API contracts or deployment policies.

## 11. Recommended Future Refactors

- Split API definitions into dedicated route modules by domain.
- Add Pydantic response models for stronger contracts.
- Add test coverage for provider-specific normalization branches.
- Add structured logging and request IDs.
