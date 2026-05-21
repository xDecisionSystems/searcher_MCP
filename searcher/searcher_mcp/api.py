from typing import Any

from fastapi import FastAPI, Query

from .config import VERSION_NAME
from .services.page import fetch_page as fetch_page_service
from .services.page import review_page as review_page_service
from .services.pdf import download_pdf as download_pdf_service
from .services.search import (
    search_google_scholar as search_google_scholar_service,
    search_ieeexplore as search_ieeexplore_service,
    search_scholar as search_scholar_service,
    search_scopus as search_scopus_service,
    search_web_of_science as search_web_of_science_service,
)

app = FastAPI(title="Searcher MCP API", version=VERSION_NAME)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version_name": VERSION_NAME}


@app.get("/fetch_page")
def fetch_page(
    url: str,
    include_html: bool = Query(default=False),
    max_chars: int = Query(default=12000, ge=500, le=100000),
) -> dict[str, Any]:
    return fetch_page_service(url=url, include_html=include_html, max_chars=max_chars)


@app.get("/review_page")
def review_page(
    url: str,
    include_html: bool = Query(default=False),
    max_chars: int = Query(default=12000, ge=500, le=100000),
) -> dict[str, Any]:
    return review_page_service(url=url, include_html=include_html, max_chars=max_chars)


@app.get("/search_scholar")
def search_scholar(
    query: str,
    limit: int = Query(default=5, ge=1, le=20),
    provider: str = Query(default="auto"),
    start_record: int = Query(default=1, ge=1, le=2000),
    wos_page: int = Query(default=1, ge=1, le=1000),
    scopus_start: int = Query(default=0, ge=0, le=6000),
) -> dict[str, Any]:
    return search_scholar_service(
        query=query,
        limit=limit,
        provider=provider,
        start_record=start_record,
        wos_page=wos_page,
        scopus_start=scopus_start,
    )


@app.get("/search_scopus")
def search_scopus(
    query: str,
    limit: int = Query(default=5, ge=1, le=25),
    start: int = Query(default=0, ge=0, le=6000),
) -> dict[str, Any]:
    return search_scopus_service(query=query, limit=limit, start=start)


@app.get("/search_google_scholar")
def search_google_scholar(
    query: str,
    limit: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    return search_google_scholar_service(query=query, limit=limit)


@app.get("/search_ieeexplore")
def search_ieeexplore(
    query: str,
    limit: int = Query(default=5, ge=1, le=20),
    start_record: int = Query(default=1, ge=1, le=2000),
) -> dict[str, Any]:
    return search_ieeexplore_service(query=query, limit=limit, start_record=start_record)


@app.get("/search_web_of_science")
def search_web_of_science(
    query: str,
    limit: int = Query(default=5, ge=1, le=20),
    page: int = Query(default=1, ge=1, le=1000),
) -> dict[str, Any]:
    return search_web_of_science_service(query=query, limit=limit, page=page)


@app.get("/download_pdf")
def download_pdf(url: str) -> dict[str, int | str]:
    return download_pdf_service(url=url)
