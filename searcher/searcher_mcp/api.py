from typing import Annotated, Any

from fastapi import Body, FastAPI, Query
from fastapi_mcp import FastApiMCP

from .config import VERSION_NAME
from .services.page import fetch_page as fetch_page_service
from .services.page import review_page as review_page_service
from .services.pdf import download_pdf as download_pdf_service
from .services.search import (
    download_ebsco_paper as download_ebsco_paper_service,
    download_ebsco_papers as download_ebsco_papers_service,
    search_ebsco_browser as search_ebsco_browser_service,
    search_google_scholar_browser as search_google_scholar_browser_service,
    search_ieeexplore as search_ieeexplore_service,
    search_sciencedirect as search_sciencedirect_service,
    search_scopus as search_scopus_service,
    search_semantic_scholar as search_semantic_scholar_service,
    search_web_of_science as search_web_of_science_service,
)

app = FastAPI(
    title="Searcher MCP API",
    description=(
        "Scholarly paper search and retrieval service. "
        "Search across Google Scholar, EBSCO, IEEE Xplore, "
        "Web of Science, and ScienceDirect. Fetch web pages and download PDFs."
    ),
    version=VERSION_NAME,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version_name": VERSION_NAME}


@app.get("/fetch_page")
def fetch_page(
    url: str,
    include_html: bool = Query(default=False),
    max_chars: int = Query(default=12000, ge=500),
) -> dict[str, Any]:
    return fetch_page_service(url=url, include_html=include_html, max_chars=max_chars)


@app.get("/review_page")
def review_page(
    url: str,
    include_html: bool = Query(default=False),
    max_chars: int = Query(default=12000, ge=500),
) -> dict[str, Any]:
    return review_page_service(url=url, include_html=include_html, max_chars=max_chars)


@app.get("/search_scopus")
def search_scopus(
    query: str,
    limit: int = Query(default=500, ge=1, description="Maximum number of results to return. Fetched in pages of 25."),
    start: int = Query(default=0, ge=0),
    year_low: int | None = Query(default=None, description="Earliest publication year (inclusive)."),
    year_high: int | None = Query(default=None, description="Latest publication year (inclusive)."),
    subj: str | None = Query(default="ENGI", description="Subject area code (e.g. ENGI, COMP, MATE, PHYS). See Scopus subject list."),
) -> dict[str, Any]:
    """Search Scopus (Elsevier) via the Scopus Search API.

    Supports Boolean queries. Results sorted by relevance. Paginates automatically
    to return up to limit results. Use subj to filter by subject area
    (ENGI=Engineering, COMP=Computer Science, MATE=Materials Science, etc).
    """
    return search_scopus_service(query=query, limit=limit, start=start, year_low=year_low, year_high=year_high, subj=subj)


@app.get("/search_sciencedirect")
def search_sciencedirect(
    query: str,
    limit: int = Query(default=20, ge=1),
    start: int = Query(default=0, ge=0),
    year_low: int | None = Query(default=None, description="Earliest publication year (inclusive)."),
    year_high: int | None = Query(default=None, description="Latest publication year (inclusive)."),
) -> dict[str, Any]:
    """Search ScienceDirect (Elsevier) via the Elsevier API."""
    return search_sciencedirect_service(query=query, limit=limit, start=start, year_low=year_low, year_high=year_high)


@app.get("/search_semantic_scholar")
def search_semantic_scholar(
    query: str,
    limit: int = Query(default=10, ge=1),
) -> dict[str, Any]:
    """Search Semantic Scholar via their public API."""
    return search_semantic_scholar_service(query=query, limit=limit)


@app.get("/search_ebsco")
def search_ebsco(
    query: str,
    limit: int = Query(default=100, ge=1),
    year_low: int | None = Query(default=None, description="Earliest publication year (inclusive)."),
    year_high: int | None = Query(default=None, description="Latest publication year (inclusive)."),
) -> dict[str, Any]:
    """Search EBSCO Research by driving the real Chromium browser.

    Requires an active institutional browser session. If access is blocked,
    open noVNC, log in through the institution portal, then retry.
    Returns results in the same schema as other search endpoints.
    """
    return search_ebsco_browser_service(
        query=query,
        limit=limit,
        year_low=year_low,
        year_high=year_high,
    )


@app.get("/download_ebsco_paper")
def download_ebsco_paper(
    url: str = Query(..., description="EBSCO paper detail page URL (research.ebsco.com/c/.../search/details/...)."),
) -> dict[str, Any]:
    """Download a single paper from an EBSCO detail page URL.

    Navigates to the detail page, clicks Download twice (first opens popup,
    second confirms), then captures and saves the PDF.
    """
    return download_ebsco_paper_service(url=url)


@app.post("/download_ebsco_papers")
def download_ebsco_papers(
    urls: list[str] = Body(..., description="List of EBSCO paper detail page URLs."),
) -> dict[str, Any]:
    """Download multiple EBSCO papers sequentially by their detail page URLs.

    Pass a JSON array of EBSCO detail page URLs. Each is downloaded in order.
    Returns completed downloads and any failures.
    """
    return download_ebsco_papers_service(urls=urls)


@app.get("/search_google_scholar_browser")
def search_google_scholar_browser(
    query: str,
    limit: int = Query(default=200, ge=1),
    start_index: int = Query(default=0, ge=0, description="Result offset for pagination."),
    year_low: int | None = Query(default=None, description="Earliest publication year (inclusive)."),
    year_high: int | None = Query(default=None, description="Latest publication year (inclusive)."),
    exclude_domains: Annotated[list[str] | None, Query(description="Domains to exclude. Defaults to researchgate.net, books.google.com, search.proquest.com. Pass empty list to disable filtering.")] = None,
) -> dict[str, Any]:
    """Search Google Scholar by driving the real Chromium browser.

    Unlike /search_google_scholar (which uses the scholarly library and is prone to
    CAPTCHA blocks), this endpoint navigates the browser_worker's persistent Chromium
    instance. After solving a CAPTCHA once via noVNC, the session persists for subsequent
    calls. Returns results in the same schema as /search_google_scholar.
    """
    return search_google_scholar_browser_service(
        query=query,
        limit=limit,
        start_index=start_index,
        year_low=year_low,
        year_high=year_high,
        exclude_domains=exclude_domains,
    )


@app.get("/search_ieeexplore")
def search_ieeexplore(
    query: str,
    limit: int = Query(default=5, ge=1),
    start_record: int = Query(default=1, ge=1),
) -> dict[str, Any]:
    return search_ieeexplore_service(query=query, limit=limit, start_record=start_record)


@app.get("/search_web_of_science")
def search_web_of_science(
    query: str,
    limit: int = Query(default=10, ge=1),
    year_low: int | None = Query(default=None, description="Earliest publication year (inclusive)."),
    year_high: int | None = Query(default=None, description="Latest publication year (inclusive)."),
) -> dict[str, Any]:
    """Search Web of Science by driving the real Chromium browser."""
    return search_web_of_science_service(query=query, limit=limit, year_low=year_low, year_high=year_high)


@app.get("/download_pdf")
def download_pdf(url: str) -> dict[str, int | str]:
    return download_pdf_service(url=url)


# ─── MCP server ───────────────────────────────────────────────────────────────
# Mounts at /mcp — exposes all endpoints above as MCP tools.
# Claude Code config: { "url": "http://<host>:8000/mcp" }
mcp = FastApiMCP(
    app,
    name="Searcher MCP",
    description=(
        "Search and retrieve academic papers from Semantic Scholar, Google Scholar, "
        "IEEE Xplore, Web of Science, and ScienceDirect. Also fetches web pages and downloads PDFs."
    ),
    exclude_operations=["health"],
)
mcp.mount()
