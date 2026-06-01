from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Body, FastAPI, Query
from starlette.responses import FileResponse

from .config import VERSION_NAME

_STATIC_DIR = Path(__file__).resolve().parent / "static"
from .services.atrd import download_atrd_paper as download_atrd_paper_service
from .services.atrd import search_atrd_papers as search_atrd_papers_service
from .services.page import fetch_page as fetch_page_service
from .services.page import review_page as review_page_service
from .services.pdf import download_pdf as download_pdf_service
from .services.search import (
    download_ebsco_paper as download_ebsco_paper_service,
    download_ebsco_papers as download_ebsco_papers_service,
    search_ebsco_browser as search_ebsco_browser_service,
    search_google_scholar_browser as search_google_scholar_browser_service,
    search_ieeexplore as search_ieeexplore_service,
    search_openalex as search_openalex_service,
    search_sciencedirect as search_sciencedirect_service,
    search_scopus as search_scopus_service,
    search_semantic_scholar as search_semantic_scholar_service,
    search_web_of_science as search_web_of_science_service,
)

app = FastAPI(
    title="Searcher API",
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


@app.get("/api-reference", response_class=FileResponse, include_in_schema=False)
def api_reference() -> FileResponse:
    """Serve the static HTML API reference page."""
    return FileResponse(_STATIC_DIR / "api_reference.html", media_type="text/html")


@app.get("/llms.txt", response_class=FileResponse, include_in_schema=False)
def llms_txt() -> FileResponse:
    """Serve the LLM-friendly plain-text API reference (llms.txt spec)."""
    return FileResponse(_STATIC_DIR / "llms.txt", media_type="text/plain; charset=utf-8")


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
    limit: int = Query(default=200, ge=1, description="Maximum number of results to return. Fetched in pages of 25."),
    start: int = Query(default=0, ge=0),
    year_low: int | None = Query(default=None, description="Earliest publication year (inclusive)."),
    year_high: int | None = Query(default=None, description="Latest publication year (inclusive)."),
    subj: str | None = Query(default="ENGI", description="Subject area code (e.g. ENGI, COMP, MATE, PHYS). See Scopus subject list."),
    include_abstract: bool = Query(default=True, description="If true (default), fetch the full abstract for each result via the Abstract Retrieval API. Makes one extra API call per result — use a small limit when fetching many results."),
) -> dict[str, Any]:
    """Search Scopus (Elsevier) via the Scopus Search API.

    Supports Boolean queries. Results sorted by relevance. Paginates automatically
    to return up to limit results. Use subj to filter by subject area
    (ENGI=Engineering, COMP=Computer Science, MATE=Materials Science, etc).

    Abstracts are fetched by default via the Abstract Retrieval API (one extra call per result).
    Set include_abstract=false to skip abstract fetching for faster bulk retrieval.
    """
    return search_scopus_service(query=query, limit=limit, start=start, year_low=year_low, year_high=year_high, subj=subj, include_abstract=include_abstract)


@app.get("/search_sciencedirect")
def search_sciencedirect(
    query: str,
    limit: int = Query(default=200, ge=1),
    start: int = Query(default=0, ge=0),
    year_low: int | None = Query(default=None, description="Earliest publication year (inclusive)."),
    year_high: int | None = Query(default=None, description="Latest publication year (inclusive)."),
) -> dict[str, Any]:
    """Search ScienceDirect (Elsevier) via the Elsevier API."""
    return search_sciencedirect_service(query=query, limit=limit, start=start, year_low=year_low, year_high=year_high)


@app.get("/search_semantic_scholar")
def search_semantic_scholar(
    query: str,
    limit: int = Query(default=200, ge=1),
) -> dict[str, Any]:
    """Search Semantic Scholar via their public API."""
    return search_semantic_scholar_service(query=query, limit=limit)


@app.get("/search_openalex")
def search_openalex(
    query: str,
    limit: int = Query(default=200, ge=1, description="Maximum number of results to return. Fetched in pages of 100."),
    year_low: int | None = Query(default=None, description="Earliest publication year (inclusive)."),
    year_high: int | None = Query(default=None, description="Latest publication year (inclusive)."),
    is_oa: bool | None = Query(default=None, description="If true, restrict to open access works only."),
    work_type: str | None = Query(default=None, description="Filter by work type: article, book, dataset, preprint, review, etc."),
) -> dict[str, Any]:
    """Search OpenAlex via their public Works API.

    OpenAlex is a free, open index of 250M+ scholarly works across all disciplines.
    Abstracts are always included in results. Supports Boolean operators in query.
    Paginates automatically using cursor-based pagination.
    Set is_oa=true to restrict to open access works with PDF links.
    """
    return search_openalex_service(
        query=query,
        limit=limit,
        year_low=year_low,
        year_high=year_high,
        is_oa=is_oa,
        work_type=work_type,
    )


@app.get("/search_ebsco")
def search_ebsco(
    query: str,
    limit: int = Query(default=200, ge=1),
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
    limit: int = Query(default=200, ge=1, description="Maximum results to return. Fetched in pages of 200."),
    start_record: int = Query(default=1, ge=1, description="Sequence number of first record (1-based)."),
    year_low: int | None = Query(default=None, description="Earliest publication year (inclusive)."),
    year_high: int | None = Query(default=None, description="Latest publication year (inclusive)."),
    content_type: str | None = Query(default=None, description="Filter by content type: Books, Conferences, Courses, Early Access, Journals, Magazines, Standards."),
    open_access: bool | None = Query(default=None, description="If true, restrict to open access articles only."),
    sort_field: Literal["article_number", "article_title", "publication_title"] | None = Query(default=None, description="Sort field: article_number, article_title, publication_title."),
    sort_order: Literal["asc", "desc"] | None = Query(default=None, description="Sort direction: asc or desc."),
    author: str | None = Query(default=None, min_length=3, description="Filter by author name (first or last, min 3 chars)."),
) -> dict[str, Any]:
    """Search IEEE Xplore via the IEEE Xplore Metadata API.

    Supports Boolean operators (AND, OR, NOT) in query. Paginates automatically
    in pages of 200 (the API maximum) to reach the requested limit.
    """
    return search_ieeexplore_service(
        query=query,
        limit=limit,
        start_record=start_record,
        year_low=year_low,
        year_high=year_high,
        content_type=content_type,
        open_access=open_access,
        sort_field=sort_field,
        sort_order=sort_order,
        author=author,
    )


@app.get("/search_web_of_science")
def search_web_of_science(
    query: str,
    limit: int = Query(default=200, ge=1),
    year_low: int | None = Query(default=None, description="Earliest publication year (inclusive)."),
    year_high: int | None = Query(default=None, description="Latest publication year (inclusive)."),
) -> dict[str, Any]:
    """Search Web of Science by driving the real Chromium browser."""
    return search_web_of_science_service(query=query, limit=limit, year_low=year_low, year_high=year_high)


@app.get("/download_pdf")
def download_pdf(url: str) -> dict[str, int | str]:
    return download_pdf_service(url=url)


@app.get("/search_atrd_papers")
def search_atrd_papers(
    url: str = Query(..., description="URL of an ATRD symposium papers-and-presentations page."),
) -> dict[str, Any]:
    """Return metadata for all papers from an ATRD symposium papers page.

    Fetches and parses the page directly (no browser required).
    Returns title, authors, section/topic, best-paper flag, and Google Drive
    links for the full paper and presentation slide deck (where available).
    Does not download any files.
    """
    return search_atrd_papers_service(url=url)


@app.post("/download_atrd_paper", response_class=FileResponse)
def download_atrd_paper(
    paper: Annotated[dict[str, Any], Body(..., description="A single paper record returned by /search_atrd_papers.")],
) -> FileResponse:
    """Download the full-paper PDF for a single ATRD paper and return it as a file.

    Pass a paper record exactly as returned by /search_atrd_papers.
    The full_paper_url field is used to fetch the PDF from Google Drive.
    The file is cached under <DOWNLOAD_DIR>/atrd/; calling again with the
    same record skips the download and serves the cached file.
    """
    result = download_atrd_paper_service(paper)
    return FileResponse(
        path=result["local_path"],
        media_type="application/pdf",
        filename=Path(result["local_path"]).name,
    )

