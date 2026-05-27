from typing import Any


from bs4 import BeautifulSoup
from fastapi import HTTPException

from ..config import (
    BROWSER_WORKER_URL,
    ELSEVIER_API_KEY,
    IEEE_XPLORE_API_KEY,
    SEMANTIC_SCHOLAR_API_KEY,
)
from ..http_client import request_json, session

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
    from urllib.parse import urlparse  # noqa: PLC0415
    return urlparse(url).netloc.lower()


def _search_semantic_scholar(query: str, limit: int) -> dict[str, Any]:
    import threading, time  # noqa: PLC0415
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
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("abstract", "") or "",
            "publication_year": item.get("year"),
            "authors": authors,
            "citation_count": item.get("citationCount"),
            "source": item.get("venue"),
            "pdf_link": open_access_pdf.get("url", "") if isinstance(open_access_pdf, dict) else "",
        })
    return {"total_records": payload.get("total"), "results": results}


def search_semantic_scholar(query: str, limit: int) -> dict[str, Any]:
    data = _search_semantic_scholar(query=query, limit=limit)
    return {"provider": "semantic_scholar", "query": query, **data}


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
    except Exception as exc:
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
            results.append({
                "title": title,
                "url": url,
                "snippet": snippet,
                "publication_year": pub_year,
                "authors": authors,
                "source": source,
                "doi": doi,
                "pdf_link": "",
            })
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
    for i, item in enumerate((search_results.get("entry") or [])[:limit], start + 1):
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
                "index": i,
                "title": item.get("dc:title", ""),
                "url": url,
                "snippet": item.get("dc:description", ""),
                "publication_year": pub_year,
                "authors": authors,
                "doi": doi,
                "pdf_link": "",
                "source": item.get("prism:publicationName", ""),
            }
        )

    return {"start": start, "total_records": total_records, "results": results}


def search_sciencedirect(query: str, limit: int, start: int, year_low: int | None = None, year_high: int | None = None) -> dict[str, Any]:
    data = _search_sciencedirect(query=query, limit=limit, start=start, year_low=year_low, year_high=year_high)
    return {"provider": "sciencedirect", "query": query, **data}


def _search_scopus(
    query: str,
    limit: int,
    start: int,
    year_low: int | None = None,
    year_high: int | None = None,
    subj: str | None = None,
) -> dict[str, Any]:
    if not ELSEVIER_API_KEY:
        raise HTTPException(status_code=400, detail="ELSEVIER_API_KEY is not configured.")

    params: dict[str, Any] = {
        "query": query,
        "count": limit,
        "start": start,
        "sort": "relevancy",
        "view": "COMPLETE",
    }
    if year_low or year_high:
        lo = year_low or 1900
        hi = year_high or 9999
        params["date"] = f"{lo}-{hi}"
    if subj:
        params["subj"] = subj.upper()

    payload = request_json(
        "https://api.elsevier.com/content/search/scopus",
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
    for i, item in enumerate((search_results.get("entry") or [])[:limit], start + 1):
        if not isinstance(item, dict):
            continue

        cover_date = item.get("prism:coverDate", "")
        pub_year: int | None = None
        if cover_date and len(cover_date) >= 4:
            try:
                pub_year = int(cover_date[:4])
            except ValueError:
                pass

        # Authors: COMPLETE view returns dc:creator (first author) or author list.
        creator = item.get("dc:creator", "")
        authors = [a.strip() for a in creator.split(";") if a.strip()] if creator else []

        # URL: prefer DOI, then Scopus abstract link from the link array.
        doi = item.get("prism:doi", "")
        url = f"https://doi.org/{doi}" if doi else ""
        if not url:
            for link in item.get("link", []):
                if isinstance(link, dict) and link.get("@ref") == "scopus":
                    url = link.get("@href", "")
                    break

        results.append({
            "index": i,
            "title": item.get("dc:title", ""),
            "url": url,
            "snippet": item.get("dc:description", ""),
            "publication_year": pub_year,
            "authors": authors,
            "doi": doi,
            "pdf_link": "",
            "source": item.get("prism:publicationName", ""),
            "cited_by": item.get("citedby-count"),
        })

    return {"start": start, "total_records": total_records, "results": results}


def search_scopus(
    query: str,
    limit: int,
    start: int,
    year_low: int | None = None,
    year_high: int | None = None,
    subj: str | None = None,
) -> dict[str, Any]:
    data = _search_scopus(query=query, limit=limit, start=start, year_low=year_low, year_high=year_high, subj=subj)
    return {"provider": "scopus", "query": query, **data}


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
            results.append({
                "title": title,
                "url": url,
                "snippet": snippet,
                "publication_year": pub_year,
                "authors": authors,
                "source": source,
                "doi": doi,
                "pdf_link": "",
            })

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
    return {"provider": "ebsco_browser", "query": query, **data}


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
    return {"provider": "google_scholar_browser", "query": query, **data}


def search_ieeexplore(query: str, limit: int, start_record: int) -> dict[str, Any]:
    data = _search_ieeexplore(query=query, limit=limit, start_record=start_record)
    return {"provider": "ieeexplore", "query": query, **data}


def search_web_of_science(
    query: str,
    limit: int,
    year_low: int | None = None,
    year_high: int | None = None,
) -> dict[str, Any]:
    data = _search_web_of_science_browser(query=query, limit=limit, year_low=year_low, year_high=year_high)
    return {"provider": "web_of_science_browser", "query": query, **data}
