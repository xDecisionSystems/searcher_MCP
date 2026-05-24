import threading
import time
from typing import Any


from bs4 import BeautifulSoup
from fastapi import HTTPException

from ..config import (
    BROWSER_WORKER_URL,
    ELSEVIER_API_KEY,
    IEEE_XPLORE_API_KEY,
    SEMANTIC_SCHOLAR_API_KEY,
    SERPAPI_API_KEY,
    WEB_OF_SCIENCE_API_KEY,
)
from ..http_client import request_json, session

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


_DEFAULT_EXCLUDE_DOMAINS: list[str] = [
    "books.google.com",
]


def _url_domain(url: str) -> str:
    from urllib.parse import urlparse  # noqa: PLC0415
    return urlparse(url).netloc.lower()


def _search_scholar_scholarly(
    query: str,
    limit: int,
    start_index: int = 0,
    year_low: int | None = None,
    year_high: int | None = None,
    exclude_domains: list[str] | None = None,
) -> dict[str, Any]:
    try:
        from scholarly import scholarly as _scholarly  # noqa: PLC0415
    except ImportError:
        raise HTTPException(status_code=500, detail="scholarly package is not installed.")

    blocked = set(exclude_domains if exclude_domains is not None else _DEFAULT_EXCLUDE_DOMAINS)

    results: list[dict[str, Any]] = []
    try:
        search_iter = _scholarly.search_pubs(
            query,
            start_index=start_index,
            year_low=year_low,
            year_high=year_high,
        )
        # Pull up to limit*3 candidates so filtering doesn't leave us short.
        candidates_checked = 0
        max_candidates = limit * 3
        while len(results) < limit and candidates_checked < max_candidates:
            try:
                item = next(search_iter)
            except StopIteration:
                break
            candidates_checked += 1

            pub_url = item.get("pub_url", "") or item.get("eprint_url", "") or ""
            if blocked and _url_domain(pub_url) in blocked:
                continue

            bib = item.get("bib", {})
            author_field = bib.get("author", "")
            if isinstance(author_field, str):
                authors = [a.strip() for a in author_field.split(" and ") if a.strip()]
            elif isinstance(author_field, list):
                authors = [str(a).strip() for a in author_field if str(a).strip()]
            else:
                authors = []

            year_raw = bib.get("pub_year", "")
            try:
                pub_year = int(str(year_raw).strip())
            except (TypeError, ValueError):
                pub_year = None

            results.append(
                {
                    "title": bib.get("title", ""),
                    "url": pub_url,
                    "snippet": bib.get("abstract", ""),
                    "publication_year": pub_year,
                    "authors": authors,
                    "source": bib.get("venue", ""),
                    "citation_count": item.get("num_citations"),
                    "pdf_link": item.get("eprint_url", ""),
                }
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"scholarly search failed: {exc}") from exc

    return {"total_records": None, "results": results}


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
    elif provider == "google_scholar_scholarly":
        data = _search_scholar_scholarly(query=query, limit=limit)
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
                "Invalid provider. Use auto, semantic_scholar, google_scholar_scholarly, "
                "google_scholar_serpapi, ieeexplore, web_of_science, or scopus."
            ),
        )

    return {"provider": provider, "query": query, **data}


def _fetch_scholar_pages_via_browser(
    query: str,
    limit: int,
    start_index: int = 0,
    year_low: int | None = None,
    year_high: int | None = None,
) -> list[str]:
    """Drive browser_worker to search Scholar and return a list of page HTML strings."""
    params: dict[str, Any] = {
        "query": query,
        "limit": limit,
        "start_index": start_index,
        "page_delay_seconds": 1.0,
    }
    if year_low is not None:
        params["year_low"] = year_low
    if year_high is not None:
        params["year_high"] = year_high
    try:
        resp = session.get(
            f"{BROWSER_WORKER_URL}/search_google_scholar",
            params=params,
            timeout=600,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"browser_worker scholar search failed: {exc}") from exc
    pages = data.get("pages_html", [])
    if not pages:
        raise HTTPException(
            status_code=503,
            detail="Scholar returned no pages. Open noVNC, solve any CAPTCHA, then retry.",
        )
    return pages


_re_year = __import__("re").compile(r"\b(?:19|20)\d{2}\b")
_re_cite = __import__("re").compile(r"Cited by (\d+)")


def _parse_scholar_results_page(html: str) -> list[dict[str, Any]]:
    """Parse a Google Scholar results page and extract paper metadata."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, Any]] = []

    for div in soup.select("div.gs_r.gs_or.gs_scl"):
        title_tag = div.select_one("h3.gs_rt a")
        title = title_tag.get_text(" ", strip=True) if title_tag else ""
        url = str(title_tag.get("href", "")) if title_tag else ""

        snippet_tag = div.select_one("div.gs_rs")
        snippet = snippet_tag.get_text(" ", strip=True) if snippet_tag else ""

        # Preserve raw bytes so \xa0 separators are intact for splitting.
        meta_tag = div.select_one("div.gs_a")
        meta_raw = meta_tag.get_text("", strip=False) if meta_tag else ""

        # Scholar meta: "A Author, B Author\xa0- Venue, YYYY - Publisher"
        # \xa0- is the reliable author/venue boundary.
        meta_parts = meta_raw.split("\xa0-", maxsplit=1)
        author_segment = meta_parts[0]
        remainder = meta_parts[1] if len(meta_parts) > 1 else ""

        # Year: first 4-digit year anywhere in the meta.
        pub_year: int | None = None
        year_match = _re_year.search(meta_raw)
        if year_match:
            pub_year = int(year_match.group(0))

        # Authors: comma-split the author segment; drop ellipsis and year-only tokens.
        authors = [
            a.strip() for a in author_segment.split(",")
            if a.strip() and a.strip() != "\u2026" and not _re_year.fullmatch(a.strip())
        ]

        # Source: strip trailing " - Publisher" from remainder, drop year.
        source = ""
        if remainder:
            src = remainder.rsplit(" - ", maxsplit=1)[0]
            src = _re_year.sub("", src).strip(" ,")
            source = src

        # Citation count
        citation_count: int | None = None
        for a in div.select("a"):
            text = a.get_text(strip=True)
            cite_match = _re_cite.match(text)
            if cite_match:
                citation_count = int(cite_match.group(1))
                break

        # PDF link from left-hand gs_or_ggsm block
        pdf_link = ""
        pdf_tag = div.select_one("div.gs_or_ggsm a")
        if pdf_tag:
            pdf_link = str(pdf_tag.get("href", ""))

        if title or url:
            results.append({
                "title": title,
                "url": url,
                "snippet": snippet,
                "publication_year": pub_year,
                "authors": authors,
                "source": source,
                "citation_count": citation_count,
                "pdf_link": pdf_link,
            })

    return results


def _search_google_scholar_browser(
    query: str,
    limit: int,
    start_index: int = 0,
    year_low: int | None = None,
    year_high: int | None = None,
    exclude_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Search Google Scholar by driving the real Chromium browser.

    Delegates to browser_worker which runs a single persistent Playwright session:
    navigate → scrape → click Next → wait 1s → scrape → repeat.
    """
    blocked = set(exclude_domains if exclude_domains is not None else _DEFAULT_EXCLUDE_DOMAINS)

    pages_html = _fetch_scholar_pages_via_browser(
        query=query,
        limit=limit,
        start_index=start_index,
        year_low=year_low,
        year_high=year_high,
    )

    results: list[dict[str, Any]] = []
    for html in pages_html:
        for item in _parse_scholar_results_page(html):
            if len(results) >= limit:
                break
            pub_url = item.get("url", "")
            if blocked and _url_domain(pub_url) in blocked:
                continue
            item["index"] = len(results) + 1
            results.append(item)
        if len(results) >= limit:
            break

    return {"total_records": None, "results": results}


def search_google_scholar(
    query: str,
    limit: int,
    start_index: int = 0,
    year_low: int | None = None,
    year_high: int | None = None,
    exclude_domains: list[str] | None = None,
) -> dict[str, Any]:
    data = _search_scholar_scholarly(
        query=query,
        limit=limit,
        start_index=start_index,
        year_low=year_low,
        year_high=year_high,
        exclude_domains=exclude_domains,
    )
    return {"provider": "google_scholar_scholarly", "query": query, **data}


def search_google_scholar_browser(
    query: str,
    limit: int,
    start_index: int = 0,
    year_low: int | None = None,
    year_high: int | None = None,
    exclude_domains: list[str] | None = None,
) -> dict[str, Any]:
    data = _search_google_scholar_browser(
        query=query,
        limit=limit,
        start_index=start_index,
        year_low=year_low,
        year_high=year_high,
        exclude_domains=exclude_domains,
    )
    return {"provider": "google_scholar_browser", "query": query, **data}


def search_ieeexplore(query: str, limit: int, start_record: int) -> dict[str, Any]:
    data = _search_ieeexplore(query=query, limit=limit, start_record=start_record)
    return {"provider": "ieeexplore", "query": query, **data}


def search_web_of_science(query: str, limit: int, page: int) -> dict[str, Any]:
    data = _search_web_of_science(query=query, limit=limit, page=page)
    return {"provider": "web_of_science", "query": query, **data}
