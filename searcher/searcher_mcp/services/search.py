import threading
import time
from typing import Any

from fastapi import HTTPException

from ..config import (
    ELSEVIER_API_KEY,
    IEEE_XPLORE_API_KEY,
    SEMANTIC_SCHOLAR_API_KEY,
    SERPAPI_API_KEY,
    WEB_OF_SCIENCE_API_KEY,
)
from ..http_client import request_json

_semantic_scholar_lock = threading.Lock()
_semantic_scholar_last_call: float = 0.0
_SEMANTIC_SCHOLAR_MIN_INTERVAL = 1.0


def _semantic_scholar_throttle() -> None:
    global _semantic_scholar_last_call
    with _semantic_scholar_lock:
        now = time.monotonic()
        wait = _SEMANTIC_SCHOLAR_MIN_INTERVAL - (now - _semantic_scholar_last_call)
        if wait > 0:
            time.sleep(wait)
        _semantic_scholar_last_call = time.monotonic()


def _normalize_authors(raw: Any) -> list[str]:
    if isinstance(raw, list):
        names: list[str] = []
        for item in raw:
            if isinstance(item, str):
                value = item.strip()
                if value:
                    names.append(value)
                continue
            if not isinstance(item, dict):
                continue
            for key in ("name", "full_name", "displayName", "wosStandard"):
                value = str(item.get(key, "")).strip()
                if value:
                    names.append(value)
                    break
        return names

    if isinstance(raw, dict):
        if isinstance(raw.get("authors"), list):
            return _normalize_authors(raw["authors"])
        if isinstance(raw.get("author"), list):
            return _normalize_authors(raw["author"])

    return []


def _search_scholar_semantic(query: str, limit: int) -> dict[str, Any]:
    _semantic_scholar_throttle()
    headers: dict[str, str] = {}
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY

    payload = request_json(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={
            "query": query,
            "limit": limit,
            "fields": "title,year,authors,url,abstract,openAccessPdf,citationCount,venue",
        },
        headers=headers or None,
    )

    results: list[dict[str, Any]] = []
    for item in payload.get("data", [])[:limit]:
        authors = [author.get("name", "") for author in item.get("authors", []) if author.get("name")]
        open_access_pdf = item.get("openAccessPdf") or {}
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("abstract", "") or "",
                "publication_year": item.get("year"),
                "authors": authors,
                "citation_count": item.get("citationCount"),
                "source": item.get("venue"),
                "pdf_link": open_access_pdf.get("url", "") if isinstance(open_access_pdf, dict) else "",
            }
        )

    return {"total_records": payload.get("total"), "results": results}


def _search_scholar_serpapi(query: str, limit: int) -> dict[str, Any]:
    if not SERPAPI_API_KEY:
        raise HTTPException(status_code=400, detail="SERPAPI_API_KEY is not configured.")

    payload = request_json(
        "https://serpapi.com/search.json",
        params={
            "engine": "google_scholar",
            "q": query,
            "num": limit,
            "api_key": SERPAPI_API_KEY,
        },
    )

    results: list[dict[str, Any]] = []
    for item in payload.get("organic_results", [])[:limit]:
        resources = item.get("resources", [])
        pdf_link = ""
        if isinstance(resources, list):
            for resource in resources:
                if not isinstance(resource, dict):
                    continue
                if "pdf" in str(resource.get("file_format", "")).lower():
                    pdf_link = str(resource.get("link", ""))
                    break

        publication_info = item.get("publication_info") or {}
        author_names = _normalize_authors(publication_info.get("authors", []))

        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "publication_info": publication_info,
                "authors": author_names,
                "result_id": item.get("result_id"),
                "pdf_link": pdf_link,
            }
        )

    search_info = payload.get("search_information")
    total_records = None
    if isinstance(search_info, dict):
        total_records = search_info.get("total_results")

    return {"total_records": total_records, "results": results}


def _search_ieeexplore(query: str, limit: int, start_record: int) -> dict[str, Any]:
    if not IEEE_XPLORE_API_KEY:
        raise HTTPException(status_code=400, detail="IEEE_XPLORE_API_KEY is not configured.")

    payload = request_json(
        "https://ieeexploreapi.ieee.org/api/v1/search/articles",
        params={
            "apikey": IEEE_XPLORE_API_KEY,
            "querytext": query,
            "max_records": limit,
            "start_record": start_record,
        },
    )

    results: list[dict[str, Any]] = []
    for item in payload.get("articles", [])[:limit]:
        authors = item.get("authors", {}).get("authors", [])
        author_names = [author.get("full_name", "") for author in authors if author.get("full_name")]
        results.append(
            {
                "title": item.get("title", "") or item.get("article_title", ""),
                "url": item.get("html_url", "") or item.get("pdf_url", ""),
                "snippet": item.get("abstract", ""),
                "publication_year": item.get("publication_year"),
                "authors": author_names,
                "doi": item.get("doi"),
                "article_number": item.get("article_number"),
                "source": item.get("publication_title"),
            }
        )

    return {
        "start_record": start_record,
        "total_records": payload.get("total_records"),
        "results": results,
    }


def _search_web_of_science(query: str, limit: int, page: int) -> dict[str, Any]:
    if not WEB_OF_SCIENCE_API_KEY:
        raise HTTPException(status_code=400, detail="WEB_OF_SCIENCE_API_KEY is not configured.")

    payload = request_json(
        "https://api.clarivate.com/apis/wos-starter/v1/documents",
        params={"q": query, "limit": limit, "page": page},
        headers={"X-ApiKey": WEB_OF_SCIENCE_API_KEY, "Accept": "application/json"},
    )

    hits = payload.get("hits")
    if not isinstance(hits, list):
        hits = []

    results: list[dict[str, Any]] = []
    for item in hits[:limit]:
        if not isinstance(item, dict):
            continue

        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        identifiers = item.get("identifiers") if isinstance(item.get("identifiers"), dict) else {}
        links = item.get("links") if isinstance(item.get("links"), dict) else {}

        abstract = item.get("abstract", "")
        if isinstance(abstract, list):
            abstract = " ".join(str(part).strip() for part in abstract if str(part).strip())
        elif abstract is None:
            abstract = ""

        authors = _normalize_authors(item.get("names"))

        results.append(
            {
                "uid": item.get("uid"),
                "title": item.get("title", ""),
                "url": links.get("record", "") or links.get("url", ""),
                "snippet": str(abstract),
                "publication_year": source.get("publishYear") or item.get("publishYear"),
                "authors": authors,
                "doi": identifiers.get("doi") or item.get("doi"),
                "source": source.get("sourceTitle") or source.get("title"),
                "citation_count": item.get("timesCited"),
            }
        )

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

    return {
        "page": page,
        "total_records": metadata.get("total"),
        "results": results,
    }


def _search_scopus(query: str, limit: int, start: int) -> dict[str, Any]:
    if not ELSEVIER_API_KEY:
        raise HTTPException(status_code=400, detail="ELSEVIER_API_KEY is not configured.")

    payload = request_json(
        "https://api.elsevier.com/content/search/scopus",
        params={"query": query, "count": limit, "start": start},
        headers={"X-ELS-APIKey": ELSEVIER_API_KEY, "Accept": "application/json"},
    )

    search_results = payload.get("search-results") or {}
    total_raw = search_results.get("opensearch:totalResults")
    try:
        total_records = int(total_raw) if total_raw is not None else None
    except (TypeError, ValueError):
        total_records = None

    results: list[dict[str, Any]] = []
    for item in (search_results.get("entry") or [])[:limit]:
        if not isinstance(item, dict):
            continue

        cover_date = item.get("prism:coverDate", "")
        pub_year: int | None = None
        if cover_date and len(cover_date) >= 4:
            try:
                pub_year = int(cover_date[:4])
            except ValueError:
                pass

        creator = item.get("dc:creator", "")
        authors = [a.strip() for a in creator.split(";") if a.strip()] if creator else []

        doi = item.get("prism:doi", "")
        url = f"https://doi.org/{doi}" if doi else item.get("prism:url", "")

        results.append(
            {
                "title": item.get("dc:title", ""),
                "url": url,
                "snippet": item.get("dc:description", ""),
                "publication_year": pub_year,
                "authors": authors,
                "doi": doi,
                "source": item.get("prism:publicationName", ""),
                "citation_count": item.get("citedby-count"),
                "scopus_id": item.get("dc:identifier", ""),
            }
        )

    return {"start": start, "total_records": total_records, "results": results}


def search_scopus(query: str, limit: int, start: int) -> dict[str, Any]:
    data = _search_scopus(query=query, limit=limit, start=start)
    return {"provider": "scopus", "query": query, **data}


def search_scholar(
    query: str,
    limit: int,
    provider: str,
    start_record: int = 1,
    wos_page: int = 1,
    scopus_start: int = 0,
) -> dict[str, Any]:
    provider = provider.lower().strip()
    if provider == "auto":
        provider = "semantic_scholar"

    if provider == "semantic_scholar":
        data = _search_scholar_semantic(query=query, limit=limit)
    elif provider == "google_scholar_serpapi":
        data = _search_scholar_serpapi(query=query, limit=limit)
    elif provider == "ieeexplore":
        data = _search_ieeexplore(query=query, limit=limit, start_record=start_record)
    elif provider == "web_of_science":
        data = _search_web_of_science(query=query, limit=limit, page=wos_page)
    elif provider == "scopus":
        data = _search_scopus(query=query, limit=limit, start=scopus_start)
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid provider. Use auto, semantic_scholar, google_scholar_serpapi, "
                "ieeexplore, web_of_science, or scopus."
            ),
        )

    return {"provider": provider, "query": query, **data}


def search_google_scholar(query: str, limit: int) -> dict[str, Any]:
    data = _search_scholar_serpapi(query=query, limit=limit)
    return {"provider": "google_scholar_serpapi", "query": query, **data}


def search_ieeexplore(query: str, limit: int, start_record: int) -> dict[str, Any]:
    data = _search_ieeexplore(query=query, limit=limit, start_record=start_record)
    return {"provider": "ieeexplore", "query": query, **data}


def search_web_of_science(query: str, limit: int, page: int) -> dict[str, Any]:
    data = _search_web_of_science(query=query, limit=limit, page=page)
    return {"provider": "web_of_science", "query": query, **data}
