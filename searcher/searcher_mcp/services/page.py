import re
from typing import Any

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException

from ..config import REQUEST_TIMEOUT
from ..http_client import session
from ..utils import validate_http_url


def _extract_page_content(soup: "BeautifulSoup", max_chars: int) -> dict[str, Any]:
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""
    meta_description = ""
    meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if meta and meta.get("content"):
        meta_description = str(meta.get("content")).strip()

    body_text = soup.get_text(separator=" ", strip=True)
    if len(body_text) > max_chars:
        body_text = body_text[:max_chars]

    links: list[str] = []
    for anchor in soup.select("a[href]")[:25]:
        href = str(anchor.get("href", "")).strip()
        if href:
            links.append(href)

    return {
        "title": title,
        "meta_description": meta_description,
        "text": body_text,
        "links": links,
    }


def _review_page_content(soup: "BeautifulSoup", max_chars: int) -> dict[str, Any]:
    headings = [h.get_text(" ", strip=True) for h in soup.select("h1, h2, h3")[:15]]
    extracted = _extract_page_content(soup=soup, max_chars=max_chars)
    words = extracted["text"].split()
    return {
        **extracted,
        "word_count": len(words),
        "estimated_read_time_minutes": max(1, round(len(words) / 220)),
        "headings": headings,
    }


def _fetch_html(url: str) -> str:
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch page: {exc}") from exc
    return resp.text


def fetch_page(url: str, include_html: bool, max_chars: int) -> dict[str, Any]:
    validate_http_url(url)
    html = _fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    extracted = _extract_page_content(soup, max_chars=max_chars)
    payload: dict[str, Any] = {"url": url, **extracted}
    if include_html:
        payload["html"] = html
    return payload


def review_page(url: str, include_html: bool, max_chars: int) -> dict[str, Any]:
    validate_http_url(url)
    html = _fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    review = _review_page_content(soup=soup, max_chars=max_chars)
    payload: dict[str, Any] = {"url": url, **review}
    if include_html:
        payload["html"] = html
    return payload
