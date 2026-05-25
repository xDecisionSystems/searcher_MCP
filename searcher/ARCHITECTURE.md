# ARCHITECTURE.md

Architecture overview for the Searcher MCP FastAPI service.

## 1. High-Level Design

Single-service HTTP API built with FastAPI.

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

- FastAPI app object: defines HTTP routes and OpenAPI docs.
- Shared `requests.Session`: reused for outbound HTTP calls with a configured User-Agent.
- Provider adapters: internal functions that normalize upstream scholarly results into project JSON shapes.
- Extraction/parsing layer: uses BeautifulSoup for HTML cleanup and content extraction.
- Download manager: streams PDF bytes to disk with size checks.

## 3. Request Flow

1. FastAPI route receives and validates query parameters.
2. Route selects helper function(s).
3. Helper performs outbound HTTP request(s) with timeout.
4. Response data is normalized into deterministic JSON.
5. Errors map to HTTPException with explicit status and message.

## 4. Endpoint Map

- `/health`: lightweight liveness endpoint.
- `/search_scholar`: unified scholarly search router — Semantic Scholar, IEEE Xplore, Web of Science, and Scopus.
- `/search_google_scholar`: Google Scholar search via the `scholarly` library. Supports `limit` (up to 200), `start_index`, `year_low`, `year_high`, and `exclude_domains`.
- `/search_google_scholar_browser`: Google Scholar search using the persistent Chromium browser. Same parameters and response schema as `/search_google_scholar`. Use when `scholarly` hits CAPTCHA blocks.
- `/search_ieeexplore`: IEEE Xplore metadata search using API key authentication.
- `/search_web_of_science`: Clarivate Web of Science Starter API search using API key authentication.
- `/search_scopus`: Elsevier Scopus Search API using API key authentication.
- `/fetch_page`: retrieves HTML and returns extracted textual content.
- `/review_page`: extends fetch output with headings and readability metrics.
- `/download_pdf`: streams PDF to disk with content-type and max-size enforcement.

## 5. Provider Selection Logic

Scholar provider selection in `/search_scholar` when `provider=auto`:

1. Semantic Scholar

Explicit provider names supported by `/search_scholar`:

- `semantic_scholar`
- `ieeexplore`
- `web_of_science`
- `scopus`

Google Scholar is accessed via dedicated endpoints (`/search_google_scholar`, `/search_google_scholar_browser`) rather than through `/search_scholar`.

## 6. Configuration Model

Configuration is environment-driven:

- `IEEE_XPLORE_API_KEY`
- `SEMANTIC_SCHOLAR_API_KEY`
- `WEB_OF_SCIENCE_API_KEY`
- `ELSEVIER_API_KEY`
- `REQUEST_TIMEOUT_SECONDS`
- `PDF_MAX_MB`
- `DOWNLOAD_DIR`
- `MCP_USER_AGENT`

Root `.env.example` documents all expected variables.

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
- Working directory: `/opt/searcher/searcher`
- Env file: `/opt/searcher/.env` (shared with all services)
- Process manager: `systemd`
- App server: `uvicorn`

## 9. Security Considerations

- URL scheme validation prevents non-web schemes.
- Outbound requests use explicit timeouts.
- PDF downloads are streamed and size-bounded.
- Untrusted HTML is parsed, not executed.
- Secrets are expected in environment variables, not source control.

## 10. Exploration Directory

`../exploration/` (repository root) contains standalone scripts used to test and evaluate options being considered for integration. Scripts there are not part of the production codebase and are not subject to standard API contracts or deployment policies.
