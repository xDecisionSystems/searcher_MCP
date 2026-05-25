from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi_mcp import FastApiMCP
from pydantic import BaseModel, Field

from .config import VERSION_NAME
from .logger import tail_log
from .services.download import download_paper_via_browser, fetch_page_via_browser, search_google_scholar_via_browser
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


# ─── MCP server ───────────────────────────────────────────────────────────────
mcp = FastApiMCP(
    app,
    name="Browser Worker MCP",
    description=(
        "Download academic papers from publisher portals using a real Chromium browser. "
        "Only one download runs at a time. "
        "Call download_paper with the paper URL. "
        "If the response has status='busy', inform the user and do NOT retry until the current download finishes. "
        "If the response has status='login_required', show the user_prompt to the user "
        "and wait for them to press OK (then retry the same call) or Stop (then abort). "
        "Do not retry automatically — always wait for explicit user confirmation. "
        "If the response has status='inaccessible', inform the user that the institution "
        "does not have access to that publisher and show the 'message' field verbatim. "
        "If the response has status='no_access', inform the user that the institution does "
        "not have access to that specific paper and show the 'message' field verbatim. "
        "If the response contains a 'strategy_hint' field, show that message to the user verbatim. "
        "Call get_logs to inspect recent download events for self-diagnosis when a "
        "download fails or behaves unexpectedly."
    ),
    exclude_operations=["health"],
)
mcp.mount()
