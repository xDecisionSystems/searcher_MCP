from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import VERSION_NAME
from .logger import tail_log
from .services.download import _validate_http_url, download_ebsco_paper, download_paper_via_browser, fetch_page_via_browser, search_ebsco_via_browser, search_google_scholar_via_browser, search_web_of_science_via_browser
from .services.recorder import (
    delete_strategy,
    get_recording_status,
    list_strategies,
    load_strategy,
    save_strategy,
    start_recording,
    stop_recording,
)

app = FastAPI(
    title="Searcher Browser Worker",
    description=(
        "Browser-automation service for downloading academic papers from authenticated "
        "publisher portals. Opens pages in a real Chromium browser and prompts "
        "interactive login through noVNC when needed."
    ),
    version=VERSION_NAME,
)


class DownloadRequest(BaseModel):
    url: str = Field(..., description="Target page URL that should eventually lead to a PDF.")
    filename: str = Field(default="", description="Optional output filename. Leave empty to auto-generate.")


class DownloadManyRequest(BaseModel):
    urls: list[str] = Field(..., description="List of paper URLs to download sequentially.")
    stop_on_login: bool = Field(
        default=True,
        description=(
            "If True (default), pause the queue when login/CAPTCHA is required and return "
            "immediately so the user can resolve it. If False, skip papers requiring login "
            "and continue with the rest."
        ),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "browser_worker", "version_name": VERSION_NAME}


@app.get("/logs")
def get_logs(
    n: int = Query(default=50, ge=1, le=500, description="Number of recent events to return."),
) -> dict[str, Any]:
    """Return the last n structured log events from the browser_worker event log.

    Use this to diagnose download failures: events include page navigation outcomes,
    HTTP status codes, which PDF selectors were tried, login detection signals,
    and final success/failure reasons.
    """
    events = tail_log(n)
    return {"count": len(events), "events": events}


@app.get("/files/{filename}")
def get_file(filename: str) -> FileResponse:
    """Download a file from the browser_worker download directory by filename."""
    from .config import DOWNLOAD_DIR
    import re
    if re.search(r"[/\\]", filename):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    path = DOWNLOAD_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found.")
    return FileResponse(path=str(path), filename=filename, media_type="application/pdf")


@app.get("/files")
def list_files() -> dict[str, Any]:
    """List all files in the browser_worker download directory."""
    from .config import DOWNLOAD_DIR
    files = []
    if DOWNLOAD_DIR.exists():
        for f in sorted(DOWNLOAD_DIR.iterdir()):
            if f.is_file():
                files.append({"filename": f.name, "size_bytes": f.stat().st_size})
    return {"count": len(files), "files": files}


@app.post("/record_session")
def record_session(
    url: str = Query(..., description="URL to navigate to at the start of recording."),
    timeout_seconds: int = Query(default=60, ge=10, le=300, description="Auto-stop after this many seconds."),
) -> dict[str, Any]:
    """Start recording your browser interactions for one download session.

    Navigate to the paper URL, perform the download manually in noVNC, then call
    POST /stop_recording (or wait for the timeout). A strategy file is saved for
    the domain and will be used automatically on future download_paper calls.
    """
    _validate_http_url(url)
    return start_recording(url=url, timeout_seconds=timeout_seconds)


@app.post("/stop_recording")
def stop_recording_endpoint() -> dict[str, Any]:
    """Stop the active recording session early and save the strategy immediately."""
    return stop_recording()


@app.get("/recording_status")
def recording_status() -> dict[str, Any]:
    """Return the current recording state (idle / recording / saved / error)."""
    return get_recording_status()


@app.get("/strategies")
def list_strategies_endpoint() -> dict[str, Any]:
    """List all saved domain strategies available for replay."""
    strategies = list_strategies()
    return {"count": len(strategies), "strategies": strategies}


@app.get("/strategies/{domain}")
def get_strategy(domain: str) -> dict[str, Any]:
    """Return the saved strategy for a domain, or 404 if not found."""
    from fastapi import HTTPException
    strategy = load_strategy(domain)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"No strategy found for domain '{domain}'.")
    return strategy


@app.put("/strategies/{domain}")
def put_strategy(domain: str, strategy: dict[str, Any]) -> dict[str, Any]:
    """Write or replace the strategy for a domain with the provided JSON body.

    The body must be a valid strategy object (same schema as GET /strategies/{domain}).
    Use this to manually clean up or replace a recorded strategy.
    """
    save_strategy(domain, strategy)
    return {"status": "saved", "domain": domain, "steps_count": len(strategy.get("steps", []))}


@app.delete("/strategies/{domain}")
def delete_strategy_endpoint(domain: str) -> dict[str, Any]:
    """Delete the saved strategy for a domain."""
    from fastapi import HTTPException
    deleted = delete_strategy(domain)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No strategy found for domain '{domain}'.")
    return {"status": "deleted", "domain": domain}


@app.get("/search_ebsco")
def search_ebsco(
    query: str = Query(..., description="Search query."),
    limit: int = Query(default=100, ge=1, description="Approximate number of results to collect (EBSCO loads in batches)."),
    year_low: int | None = Query(default=None, description="Earliest publication year (inclusive)."),
    year_high: int | None = Query(default=None, description="Latest publication year (inclusive)."),
    page_delay_seconds: float = Query(default=2.0, ge=0.5, description="Seconds to wait after clicking 'Show more results'."),
) -> dict[str, Any]:
    """Search EBSCO Research using the real Chromium browser.

    Navigates to research.ebsco.com, waits for the React SPA to render results,
    then clicks 'Show more results' until the requested limit is reached.
    Returns raw HTML snapshots for the searcher service to parse.
    Session cookies persist so institutional access stays active.
    """
    return search_ebsco_via_browser(
        query=query,
        limit=limit,
        year_low=year_low,
        year_high=year_high,
        page_delay_seconds=page_delay_seconds,
    )


@app.get("/download_ebsco_paper")
def download_ebsco_paper_endpoint(
    url: str = Query(..., description="EBSCO paper detail page URL (research.ebsco.com/c/.../search/details/...)."),
) -> dict[str, Any]:
    """Download a single paper from an EBSCO detail page.

    Navigates to the detail URL, clicks Download twice (first opens popup,
    second confirms), then captures and saves the PDF from the API response.
    Requires an active institutional browser session.
    """
    return download_ebsco_paper(url=url)


@app.post("/download_ebsco_papers")
def download_ebsco_papers(request: DownloadManyRequest) -> dict[str, Any]:
    """Download multiple EBSCO papers sequentially by their detail page URLs.

    Each URL must be an EBSCO detail page (research.ebsco.com/c/.../search/details/...).
    Returns completed downloads and any failures.
    """
    completed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for url in request.urls:
        try:
            result = download_ebsco_paper(url=url)
            completed.append({"url": url, **result})
        except HTTPException as exc:
            failed.append({"url": url, "status": "error", "message": str(exc.detail)})

    return {
        "status": "done",
        "completed": completed,
        "failed": failed,
        "total": len(request.urls),
        "succeeded": len(completed),
    }


@app.get("/search_google_scholar")
def search_google_scholar(
    query: str = Query(..., description="Search query."),
    limit: int = Query(default=200, ge=1, description="Maximum number of results to collect."),
    start_index: int = Query(default=0, ge=0, description="Result offset (multiple of 10)."),
    year_low: int | None = Query(default=None, description="Earliest publication year (inclusive)."),
    year_high: int | None = Query(default=None, description="Latest publication year (inclusive)."),
    page_delay_seconds: float = Query(default=1.0, ge=0.0, description="Seconds to wait between pages."),
) -> dict[str, Any]:
    """Search Google Scholar using the real Chromium browser.

    Navigates to the first results page, scrapes it, clicks the Next button,
    waits page_delay_seconds, then repeats until limit results are collected.
    Returns a list of raw HTML pages for the searcher service to parse.
    Session cookies persist, so a CAPTCHA solved once via noVNC stays solved.
    """
    return search_google_scholar_via_browser(
        query=query,
        limit=limit,
        start_index=start_index,
        year_low=year_low,
        year_high=year_high,
        page_delay_seconds=page_delay_seconds,
    )


@app.get("/search_web_of_science")
def search_web_of_science(
    query: str = Query(..., description="Search query."),
    limit: int = Query(default=10, ge=1, description="Number of records to export."),
    year_low: int | None = Query(default=None, description="Earliest publication year (inclusive)."),
    year_high: int | None = Query(default=None, description="Latest publication year (inclusive)."),
) -> dict[str, Any]:
    """Search Web of Science using the real Chromium browser.

    Submits the query, opens the Export overlay, selects BibTeX format,
    and downloads the exported records. Returns raw BibTeX for the searcher
    service to parse.
    """
    return search_web_of_science_via_browser(
        query=query,
        limit=limit,
        year_low=year_low,
        year_high=year_high,
    )


@app.get("/fetch_page")
def fetch_page(
    url: str = Query(..., description="URL to navigate to and return rendered HTML from."),
) -> dict[str, Any]:
    """Fetch a page using the real Chromium browser and return its rendered HTML.

    Shares the same browser session as download_paper, so cookies (e.g. a solved
    CAPTCHA) persist across calls. Use this to access pages that block plain HTTP
    requests, such as Google Scholar after CAPTCHA resolution.
    """
    return fetch_page_via_browser(url=url)


@app.post("/download_paper")
def download_paper(request: DownloadRequest) -> dict[str, Any]:
    """Download a paper via browser automation.

    On success returns the saved file path and size.

    When a login wall is detected, returns status='login_required' and a
    user_prompt asking the user to log in via noVNC then press OK to retry
    or Stop to cancel. The agent must surface that prompt to the user and,
    if the user presses OK, call this endpoint again with the same URL.
    """
    return download_paper_via_browser(url=request.url, filename=request.filename or None)


@app.post("/download_papers")
def download_papers(request: DownloadManyRequest) -> dict[str, Any]:
    """Download multiple papers sequentially, one at a time.

    Processes each URL in order. On login_required or busy, stops the queue
    immediately (if stop_on_login=True) and returns results so far plus the
    pending URLs so the user can resolve the issue and retry the remainder.

    Returns:
      - completed: list of successful download results
      - failed: list of {url, status, message} for no_access / failed
      - paused_at: URL that caused a login/CAPTCHA pause (if any)
      - pending: remaining URLs not yet attempted
      - user_prompt: prompt to show user if paused_at is set
    """
    completed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for i, url in enumerate(request.urls):
        try:
            result = download_paper_via_browser(url=url)
        except HTTPException as exc:
            result = exc.detail if isinstance(exc.detail, dict) else {"status": "error", "message": str(exc.detail)}

        status = result.get("status", "ok") if isinstance(result, dict) else "ok"

        if status in ("login_required", "busy"):
            if request.stop_on_login:
                return {
                    "status": "paused",
                    "completed": completed,
                    "failed": failed,
                    "paused_at": url,
                    "pending": request.urls[i:],
                    "user_prompt": result.get("user_prompt") or result.get("message", ""),
                }
            else:
                failed.append({"url": url, **result})
        elif status in ("no_access", "inaccessible", "failed", "error"):
            failed.append({"url": url, **result})
        else:
            completed.append(result)

    return {
        "status": "done",
        "completed": completed,
        "failed": failed,
        "paused_at": None,
        "pending": [],
    }

