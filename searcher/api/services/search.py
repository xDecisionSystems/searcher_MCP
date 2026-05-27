from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException

from ..config import (
    BROWSER_WORKER_URL,
    ELSEVIER_API_KEY,
    IEEE_XPLORE_API_KEY,
    OPENALEX_API_KEY,
    SEMANTIC_SCHOLAR_API_KEY,
)
from ..http_client import request_json, session

def _envelope(
    provider: str,
    query: str,
    results: list[dict[str, Any]],
    total_records: int | None,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "query": query,
        "search_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "total_records_available": total_records,
        "total_records_downloaded": len(results),
        "results": results,
    }


def _result(
    *,
    title: str = "",
    url: str = "",
    publication_year: int | None = None,
    authors: list[str] | None = None,
    doi: str = "",
    source: str = "",
    snippet: str = "",
    pdf_link: str = "",
    is_abstract: bool = False,
) -> dict[str, Any]:
    return {
        "title": title,
        "url": url,
        "publication_year": publication_year,
        "authors": authors or [],
        "doi": doi,
        "source": source,
        "snippet": snippet,
        "is_abstract": is_abstract,
        "pdf_link": pdf_link,
    }


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


_DEFAULT_EXCLUDE_DOMAINS: list[str] = [
    "books.google.com",
]


def _url_domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _search_semantic_scholar(query: str, limit: int) -> dict[str, Any]:
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
        authors = [a.get("name", "") for a in item.get("authors", []) if a.get("name")]
        open_access_pdf = item.get("openAccessPdf") or {}
        results.append(_result(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("abstract", "") or "",
            is_abstract=True,
            publication_year=item.get("year"),
            authors=authors,
            source=item.get("venue") or "",
            pdf_link=open_access_pdf.get("url", "") if isinstance(open_access_pdf, dict) else "",
        ))
    return {"total_records": payload.get("total"), "results": results}


def search_semantic_scholar(query: str, limit: int) -> dict[str, Any]:
    data = _search_semantic_scholar(query=query, limit=limit)
    return _envelope("semantic_scholar", query, data["results"], data.get("total_records"))


_IEEE_PAGE_SIZE = 200  # API hard cap per request


def _search_ieeexplore(
    query: str,
    limit: int,
    start_record: int,
    year_low: int | None = None,
    year_high: int | None = None,
    content_type: str | None = None,
    open_access: bool | None = None,
    sort_field: str | None = None,
    sort_order: str | None = None,
    author: str | None = None,
) -> dict[str, Any]:
    if not IEEE_XPLORE_API_KEY:
        raise HTTPException(status_code=400, detail="IEEE_XPLORE_API_KEY is not configured.")

    base_params: dict[str, Any] = {"apikey": IEEE_XPLORE_API_KEY, "querytext": query}
    if year_low is not None:
        base_params["start_year"] = year_low
    if year_high is not None:
        base_params["end_year"] = year_high
    if content_type:
        base_params["content_type"] = content_type
    if open_access:
        base_params["open_access"] = "True"
    if sort_field:
        base_params["sort_field"] = sort_field
    if sort_order:
        base_params["sort_order"] = sort_order
    if author:
        base_params["author"] = author

    results: list[dict[str, Any]] = []
    total_records: int | None = None
    offset = start_record

    while len(results) < limit:
        batch_size = min(_IEEE_PAGE_SIZE, limit - len(results))
        params = {**base_params, "max_records": batch_size, "start_record": offset}
        payload = request_json(
            "https://ieeexploreapi.ieee.org/api/v1/search/articles",
            params=params,
        )

        if total_records is None:
            total_raw = payload.get("total_records")
            try:
                total_records = int(total_raw) if total_raw is not None else None
            except (TypeError, ValueError):
                pass

        articles = payload.get("articles", [])
        if not articles:
            break

        for item in articles:
            author_names = _normalize_authors(item.get("authors"))
            doi = item.get("doi", "") or ""
            url = item.get("html_url", "") or item.get("pdf_url", "") or (f"https://doi.org/{doi}" if doi else "")
            results.append(_result(
                title=item.get("article_title", "") or item.get("title", ""),
                url=url,
                snippet=item.get("abstract", ""),
                is_abstract=True,
                publication_year=item.get("publication_year"),
                authors=author_names,
                doi=doi,
                source=item.get("publication_title") or "",
                pdf_link=item.get("pdf_url", "") or "",
            ))

        offset += len(articles)
        if len(articles) < batch_size:
            break

    return {
        "start_record": start_record,
        "total_records": total_records,
        "results": results[:limit],
    }


def _fetch_wos_bibtex_via_browser(
    query: str,
    limit: int,
    year_low: int | None = None,
    year_high: int | None = None,
) -> str:
    params: dict[str, Any] = {"query": query, "limit": limit}
    if year_low is not None:
        params["year_low"] = year_low
    if year_high is not None:
        params["year_high"] = year_high
    try:
        resp = session.get(
            f"{BROWSER_WORKER_URL}/search_web_of_science",
            params=params,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"browser_worker WoS search failed: {exc}") from exc
    bibtex = data.get("bibtex", "")
    if not bibtex:
        raise HTTPException(status_code=503, detail="Web of Science returned no records. Ensure you are logged in via noVNC and retry.")
    return bibtex


def _parse_wos_bibtex(bibtex: str) -> list[dict[str, Any]]:
    import re as _re
    results: list[dict[str, Any]] = []
    # Split on BibTeX entry boundaries.
    entries = _re.split(r"\n(?=@)", bibtex.strip())
    for entry in entries:
        if not entry.strip().startswith("@"):
            continue
        def _field(name: str) -> str:
            m = _re.search(rf"{name}\s*=\s*[{{\"](.*?)[}}\"]", entry, _re.IGNORECASE | _re.DOTALL)
            return m.group(1).strip() if m else ""

        title = _field("title")
        doi = _field("doi")
        url = f"https://doi.org/{doi}" if doi else _field("url")
        # WoS unique ID as fallback URL.
        if not url:
            uid = _field("unique-id")
            if uid:
                url = f"https://www.webofscience.com/wos/woscc/full-record/{uid}"

        year_raw = _field("year")
        try:
            pub_year: int | None = int(year_raw)
        except (ValueError, TypeError):
            pub_year = None

        # Authors: "Last, First and Last2, First2"
        author_raw = _field("author")
        authors = [a.strip() for a in _re.split(r"\s+and\s+", author_raw) if a.strip()] if author_raw else []

        source = _field("journal") or _field("booktitle") or _field("source")
        snippet = _field("abstract")

        if title or url:
            results.append(_result(
                title=title,
                url=url,
                snippet=snippet,
                is_abstract=bool(snippet),
                publication_year=pub_year,
                authors=authors,
                source=source,
                doi=doi,
            ))
    return results


def _search_web_of_science_browser(
    query: str,
    limit: int,
    year_low: int | None = None,
    year_high: int | None = None,
) -> dict[str, Any]:
    bibtex = _fetch_wos_bibtex_via_browser(query=query, limit=limit, year_low=year_low, year_high=year_high)
    results: list[dict[str, Any]] = []
    for item in _parse_wos_bibtex(bibtex):
        if len(results) >= limit:
            break
        item["index"] = len(results) + 1
        results.append(item)
        if len(results) >= limit:
            break
    return {"total_records": None, "results": results}


def _search_sciencedirect(query: str, limit: int, start: int, year_low: int | None = None, year_high: int | None = None) -> dict[str, Any]:
    if not ELSEVIER_API_KEY:
        raise HTTPException(status_code=400, detail="ELSEVIER_API_KEY is not configured.")

    params: dict[str, Any] = {"query": query, "count": limit, "start": start}
    if year_low:
        params["date"] = f"{year_low}-{year_high or 9999}"

    payload = request_json(
        "https://api.elsevier.com/content/search/sciencedirect",
        params=params,
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
        results.append(_result(
            title=item.get("dc:title", ""),
            url=url,
            snippet=item.get("dc:description", ""),
            publication_year=pub_year,
            authors=authors,
            doi=doi,
            source=item.get("prism:publicationName", ""),
        ))

    return {"start": start, "total_records": total_records, "results": results}


def search_sciencedirect(query: str, limit: int, start: int, year_low: int | None = None, year_high: int | None = None) -> dict[str, Any]:
    data = _search_sciencedirect(query=query, limit=limit, start=start, year_low=year_low, year_high=year_high)
    return _envelope("sciencedirect", query, data["results"], data.get("total_records"))


_SCOPUS_PAGE_SIZE = 25


def _scopus_parse_entries(entries: list, offset: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in entries:
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
        url = f"https://doi.org/{doi}" if doi else ""
        abstract_url = ""
        if not url:
            for link in item.get("link", []):
                if isinstance(link, dict) and link.get("@ref") == "scopus":
                    url = link.get("@href", "")
                    break
        for link in item.get("link", []):
            if isinstance(link, dict) and link.get("@ref") == "self":
                abstract_url = link.get("@href", "")
                break
        if not abstract_url:
            abstract_url = item.get("prism:url", "")
        entry = _result(
            title=item.get("dc:title", ""),
            url=url,
            publication_year=pub_year,
            authors=authors,
            doi=doi,
            source=item.get("prism:publicationName", ""),
        )
        entry["_abstract_url"] = abstract_url
        results.append(entry)
    return results


def _fetch_scopus_abstract(abstract_url: str) -> str:
    """Fetch the abstract text for a single Scopus record via the Abstract Retrieval API."""
    if not abstract_url or not ELSEVIER_API_KEY:
        return ""
    try:
        payload = request_json(
            abstract_url,
            headers={"X-ELS-APIKey": ELSEVIER_API_KEY, "Accept": "application/json"},
        )
        abstracts_retrieval = payload.get("abstracts-retrieval-response") or {}
        coredata = abstracts_retrieval.get("coredata") or {}
        return coredata.get("dc:description", "") or ""
    except HTTPException:
        return ""


def _search_scopus(
    query: str,
    limit: int,
    start: int,
    year_low: int | None = None,
    year_high: int | None = None,
    subj: str | None = None,
    include_abstract: bool = True,
) -> dict[str, Any]:
    if not ELSEVIER_API_KEY:
        raise HTTPException(status_code=400, detail="ELSEVIER_API_KEY is not configured.")

    base_params: dict[str, Any] = {
        "query": query,
        "sort": "relevancy",
        "count": _SCOPUS_PAGE_SIZE,
    }
    if year_low or year_high:
        lo = year_low or 1900
        hi = year_high or 9999
        base_params["date"] = f"{lo}-{hi}"
    if subj:
        base_params["subj"] = subj.upper()

    results: list[dict[str, Any]] = []
    total_records: int | None = None
    offset = start

    while len(results) < limit:
        params = {**base_params, "start": offset, "count": min(_SCOPUS_PAGE_SIZE, limit - len(results))}
        payload = request_json(
            "https://api.elsevier.com/content/search/scopus",
            params=params,
            headers={"X-ELS-APIKey": ELSEVIER_API_KEY, "Accept": "application/json"},
        )
        search_results = payload.get("search-results") or {}

        if total_records is None:
            total_raw = search_results.get("opensearch:totalResults")
            try:
                total_records = int(total_raw) if total_raw is not None else None
            except (TypeError, ValueError):
                pass

        entries = search_results.get("entry") or []
        if not entries:
            break

        batch = _scopus_parse_entries(entries, len(results))
        results.extend(batch)
        offset += len(entries)

        if len(entries) < _SCOPUS_PAGE_SIZE:
            break

    results = results[:limit]

    if include_abstract:
        for item in results:
            abstract_url = item.pop("_abstract_url", "")
            if abstract_url:
                abstract = _fetch_scopus_abstract(abstract_url)
                item["snippet"] = abstract
                item["is_abstract"] = bool(abstract)
    else:
        for item in results:
            item.pop("_abstract_url", None)

    return {"start": start, "total_records": total_records, "results": results}


def search_scopus(
    query: str,
    limit: int,
    start: int,
    year_low: int | None = None,
    year_high: int | None = None,
    subj: str | None = None,
    include_abstract: bool = True,
) -> dict[str, Any]:
    data = _search_scopus(query=query, limit=limit, start=start, year_low=year_low, year_high=year_high, subj=subj, include_abstract=include_abstract)
    return _envelope("scopus", query, data["results"], data.get("total_records"))


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
    except requests.RequestException as exc:
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
            results.append(_result(
                title=title,
                url=url,
                snippet=snippet,
                publication_year=pub_year,
                authors=authors,
                source=source,
                pdf_link=pdf_link,
            ))

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


def _fetch_ebsco_pages_via_browser(
    query: str,
    limit: int,
    year_low: int | None = None,
    year_high: int | None = None,
) -> list[str]:
    """Drive browser_worker to search EBSCO and return a list of HTML snapshot strings."""
    params: dict[str, Any] = {"query": query, "limit": limit}
    if year_low is not None:
        params["year_low"] = year_low
    if year_high is not None:
        params["year_high"] = year_high
    try:
        resp = session.get(
            f"{BROWSER_WORKER_URL}/search_ebsco",
            params=params,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"browser_worker EBSCO search failed: {exc}") from exc
    pages = data.get("pages_html", [])
    if not pages:
        raise HTTPException(
            status_code=503,
            detail="EBSCO returned no pages. Ensure you are logged in via noVNC and retry.",
        )
    return pages


def _parse_ebsco_results_page(html: str) -> list[dict[str, Any]]:
    """Parse an EBSCO search results HTML snapshot and extract paper metadata."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, Any]] = []

    for card in soup.find_all(attrs={"data-auto": "search-result-item"}):
        # Title and detail URL
        title_tag = card.find(attrs={"data-auto": "result-item-title__link"})
        if not title_tag:
            title_tag = card.select_one("[data-auto='result-item-title'] a") or card.select_one("h3 a")
        title = title_tag.get_text(" ", strip=True) if title_tag else ""
        url = ""
        if title_tag:
            href = str(title_tag.get("href", ""))
            if href.startswith("/"):
                url = "https://research.ebsco.com" + href
            elif href.startswith("http"):
                url = href

        # Authors
        authors: list[str] = []
        contributors = card.find(attrs={"data-auto": "result-item-metadata-content--contributors"})
        if contributors:
            for a in contributors.find_all("a"):
                name = a.get_text(" ", strip=True)
                if name:
                    authors.append(name)
            if not authors:
                text = contributors.get_text(" ", strip=True)
                authors = [a.strip() for a in text.split(";") if a.strip()]

        # Publication year
        pub_year: int | None = None
        published = card.find(attrs={"data-auto": "result-item-metadata-content--published"})
        if published:
            year_match = _re_year.search(published.get_text(" ", strip=True))
            if year_match:
                pub_year = int(year_match.group(0))
        if pub_year is None:
            year_match = _re_year.search(card.get_text(" ", strip=True))
            if year_match:
                pub_year = int(year_match.group(0))

        # Source/journal
        source = ""
        db_tag = card.find(attrs={"data-auto": "result-item-metadata-content--database-hyperlink"})
        if not db_tag:
            db_tag = card.find(attrs={"data-auto": "result-item-metadata-content--database"})
        if db_tag:
            source = db_tag.get_text(" ", strip=True)

        # Abstract/snippet
        snippet = ""
        abstract_tag = card.find(attrs={"data-auto": "abstract-content"})
        if abstract_tag:
            snippet = abstract_tag.get_text(" ", strip=True)

        # DOI
        doi = ""
        for a in card.select("a[href*='doi.org']"):
            href = str(a.get("href", ""))
            doi_match = __import__("re").search(r"10\.\d{4,}/\S+", href)
            if doi_match:
                doi = doi_match.group(0).rstrip(".")
                break

        if title or url:
            results.append(_result(
                title=title,
                url=url,
                snippet=snippet,
                publication_year=pub_year,
                authors=authors,
                source=source,
                doi=doi,
            ))

    return results


def _extract_ebsco_total(html: str) -> int | None:
    """Extract the total result count from EBSCO's result-count element."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find(attrs={"data-auto": "result-count"})
    if tag:
        text = tag.get_text(" ", strip=True)
        m = __import__("re").search(r"[\d,]+", text)
        if m:
            try:
                return int(m.group(0).replace(",", ""))
            except ValueError:
                pass
    return None


def _search_ebsco_browser(
    query: str,
    limit: int,
    year_low: int | None = None,
    year_high: int | None = None,
) -> dict[str, Any]:
    pages_html = _fetch_ebsco_pages_via_browser(
        query=query,
        limit=limit,
        year_low=year_low,
        year_high=year_high,
    )

    # Use the last snapshot — it has the most accumulated results after "Show more" clicks.
    results: list[dict[str, Any]] = []
    total_records: int | None = None
    if pages_html:
        total_records = _extract_ebsco_total(pages_html[-1])
        results = _parse_ebsco_results_page(pages_html[-1])
        results = results[:limit]
        for i, r in enumerate(results):
            r["index"] = i + 1

    return {"total_records": total_records, "results": results}


def search_ebsco_browser(
    query: str,
    limit: int,
    year_low: int | None = None,
    year_high: int | None = None,
) -> dict[str, Any]:
    data = _search_ebsco_browser(
        query=query,
        limit=limit,
        year_low=year_low,
        year_high=year_high,
    )
    return _envelope("ebsco_browser", query, data["results"], data.get("total_records"))


def download_ebsco_paper(url: str) -> dict[str, Any]:
    """Download a single EBSCO paper by its detail page URL."""
    try:
        resp = session.get(
            f"{BROWSER_WORKER_URL}/download_ebsco_paper",
            params={"url": url},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"EBSCO download failed: {exc}") from exc


def download_ebsco_papers(urls: list[str]) -> dict[str, Any]:
    """Download multiple EBSCO papers by their detail page URLs."""
    try:
        resp = session.post(
            f"{BROWSER_WORKER_URL}/download_ebsco_papers",
            json={"urls": urls},
            timeout=60 * len(urls) + 30,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"EBSCO batch download failed: {exc}") from exc


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
    return _envelope("google_scholar_browser", query, data["results"], data.get("total_records"))


def search_ieeexplore(
    query: str,
    limit: int,
    start_record: int,
    year_low: int | None = None,
    year_high: int | None = None,
    content_type: str | None = None,
    open_access: bool | None = None,
    sort_field: str | None = None,
    sort_order: str | None = None,
    author: str | None = None,
) -> dict[str, Any]:
    data = _search_ieeexplore(
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
    return _envelope("ieeexplore", query, data["results"], data.get("total_records"))


def search_web_of_science(
    query: str,
    limit: int,
    year_low: int | None = None,
    year_high: int | None = None,
) -> dict[str, Any]:
    data = _search_web_of_science_browser(query=query, limit=limit, year_low=year_low, year_high=year_high)
    return _envelope("web_of_science_browser", query, data["results"], data.get("total_records"))


_OPENALEX_PAGE_SIZE = 100  # API maximum per request
_OPENALEX_SELECT = ",".join([
    "id", "doi", "display_name", "publication_year", "cited_by_count",
    "authorships", "primary_location", "best_oa_location", "open_access",
    "abstract_inverted_index", "type",
])


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """Reconstruct abstract text from OpenAlex abstract_inverted_index format.

    The inverted index maps each word to a list of positions it appears at.
    Reconstruct by sorting words by their positions into a flat list.
    """
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, pos_list in inverted_index.items():
        for pos in pos_list:
            positions[pos] = word
    return " ".join(positions[i] for i in sorted(positions))


def _search_openalex(
    query: str,
    limit: int,
    year_low: int | None = None,
    year_high: int | None = None,
    is_oa: bool | None = None,
    work_type: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "search": query,
        "per_page": min(_OPENALEX_PAGE_SIZE, limit),
        "select": _OPENALEX_SELECT,
        "sort": "relevance_score:desc",
        "mailto": "Adan.Vela@ucf.edu",
    }
    if OPENALEX_API_KEY:
        params["api_key"] = OPENALEX_API_KEY

    filters: list[str] = []
    if year_low and year_high:
        filters.append(f"publication_year:{year_low}-{year_high}")
    elif year_low:
        filters.append(f"publication_year:>{year_low - 1}")
    elif year_high:
        filters.append(f"publication_year:<{year_high + 1}")
    if is_oa is not None:
        filters.append(f"open_access.is_oa:{'true' if is_oa else 'false'}")
    if work_type:
        filters.append(f"type:{work_type}")
    if filters:
        params["filter"] = ",".join(filters)

    results: list[dict[str, Any]] = []
    total_records: int | None = None
    cursor = "*"

    while len(results) < limit:
        params["per_page"] = min(_OPENALEX_PAGE_SIZE, limit - len(results))
        params["cursor"] = cursor
        payload = request_json(
            "https://api.openalex.org/works",
            params=params,
        )

        if total_records is None:
            meta = payload.get("meta") or {}
            total_records = meta.get("count")

        works = payload.get("results") or []
        if not works:
            break

        for item in works:
            if len(results) >= limit:
                break

            doi = (item.get("doi") or "").replace("https://doi.org/", "")
            url = f"https://doi.org/{doi}" if doi else item.get("id", "")

            # Authors from authorships list
            authors: list[str] = []
            for authorship in item.get("authorships") or []:
                author = authorship.get("author") or {}
                name = author.get("display_name", "").strip()
                if name:
                    authors.append(name)

            # Source/journal from primary_location
            source = ""
            primary_location = item.get("primary_location") or {}
            source_obj = primary_location.get("source") or {}
            if source_obj:
                source = source_obj.get("display_name", "")

            # PDF link from best_oa_location
            pdf_link = ""
            best_oa = item.get("best_oa_location") or {}
            if best_oa:
                pdf_link = best_oa.get("pdf_url", "") or ""

            # Abstract from inverted index — strip leading "Abstract" header if present
            abstract = _reconstruct_abstract(item.get("abstract_inverted_index"))
            if abstract.lower().startswith("abstract"):
                abstract = abstract[len("abstract"):].lstrip(" .:—-")

            results.append(_result(
                title=item.get("display_name", ""),
                url=url,
                snippet=abstract,
                is_abstract=bool(abstract),
                publication_year=item.get("publication_year"),
                authors=authors,
                doi=doi,
                source=source,
                pdf_link=pdf_link,
            ))

        meta = payload.get("meta") or {}
        cursor = meta.get("next_cursor", "")
        if not cursor:
            break

    return {"total_records": total_records, "results": results}


def search_openalex(
    query: str,
    limit: int,
    year_low: int | None = None,
    year_high: int | None = None,
    is_oa: bool | None = None,
    work_type: str | None = None,
) -> dict[str, Any]:
    data = _search_openalex(
        query=query,
        limit=limit,
        year_low=year_low,
        year_high=year_high,
        is_oa=is_oa,
        work_type=work_type,
    )
    return _envelope("openalex", query, data["results"], data.get("total_records"))
