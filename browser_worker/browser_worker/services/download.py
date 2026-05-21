import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from ..config import APP_USER_AGENT, DOWNLOAD_DIR, HEADLESS, MAX_DOWNLOAD_MB, REQUEST_TIMEOUT


def _validate_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid URL. Use http(s) URL.")


def _safe_filename(url: str, fallback_prefix: str = "paper") -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name.strip() or f"{fallback_prefix}-{uuid.uuid4().hex}.pdf"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name[:220]


def _unique_output_path(directory: Path, filename: str) -> Path:
    """Return a path that does not exist by appending a short UUID when needed."""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
    return directory / f"{stem}-{uuid.uuid4().hex[:8]}.pdf"


def _stream_to_disk(url: str, out_path: Path) -> int:
    """Download url via requests streaming, enforce MAX_DOWNLOAD_MB, write to out_path."""
    max_bytes = MAX_DOWNLOAD_MB * 1024 * 1024
    size = 0
    try:
        with requests.get(
            url,
            stream=True,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": APP_USER_AGENT},
            allow_redirects=True,
        ) as resp:
            resp.raise_for_status()
            with open(out_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Download exceeded configured max size ({MAX_DOWNLOAD_MB} MB).",
                        )
                    fh.write(chunk)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Download request failed: {exc}") from exc
    return size


def _extract_pdf_link(base_url: str, html: str) -> str | None:
    """Return the best PDF link found on the page, or None.

    Priority order:
    1. <a> whose href ends with .pdf (explicit extension)
    2. <a> whose link text contains "pdf" (case-insensitive)
    3. <a> whose href contains "pdf" (fallback)

    Only http/https absolute or root-relative hrefs are considered.
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[int, str]] = []

    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href", "")).strip()
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue

        lower_href = href.lower()
        link_text = anchor.get_text(" ", strip=True).lower()

        if lower_href.endswith(".pdf"):
            candidates.append((0, absolute))
        elif "pdf" in link_text:
            candidates.append((1, absolute))
        elif "pdf" in lower_href:
            candidates.append((2, absolute))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def _get_browser_context(playwright: Any) -> Any:
    """Return a browser context.

    Priority:
    1. CDP_URL set — connect to a remote Chromium instance (session lives there).
    2. SESSION_DIR set — launch a persistent local context (cookies saved to disk).
    3. Neither — launch a fresh ephemeral context per request.
    """
    from ..config import CDP_URL, HEADLESS, SESSION_DIR

    if CDP_URL:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        # Reuse the default context that Chromium was started with so the
        # persistent session (cookies, storage) is available.
        contexts = browser.contexts
        if contexts:
            return contexts[0]
        return browser.new_context(user_agent=APP_USER_AGENT)

    if SESSION_DIR is not None:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        return playwright.chromium.launch_persistent_context(
            str(SESSION_DIR),
            headless=HEADLESS,
            user_agent=APP_USER_AGENT,
        )

    browser = playwright.chromium.launch(headless=HEADLESS)
    return browser.new_context(user_agent=APP_USER_AGENT)


def download_paper_via_browser(url: str, filename: str | None = None) -> dict[str, Any]:
    _validate_http_url(url)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    base_name = filename.strip() if filename else _safe_filename(url)
    if not base_name.lower().endswith(".pdf"):
        base_name = f"{base_name}.pdf"
    base_name = re.sub(r"[^A-Za-z0-9._-]", "_", base_name)[:220]
    output_path = _unique_output_path(DOWNLOAD_DIR, base_name)

    try:
        with sync_playwright() as playwright:
            ctx = _get_browser_context(playwright)

            # persistent context acts as both browser and context
            is_persistent = not hasattr(ctx, "new_page") is False
            page = ctx.new_page()

            response = page.goto(url, wait_until="domcontentloaded", timeout=int(REQUEST_TIMEOUT * 1000))
            content_type = ""
            if response is not None:
                content_type = (response.header_value("content-type") or "").lower()

            if "pdf" in content_type:
                # Page response is directly a PDF — get the final URL and stream it
                final_url = page.url
                page.close()
                ctx.close()
                size = _stream_to_disk(final_url, output_path)
                return {
                    "path": str(output_path),
                    "filename": output_path.name,
                    "size_bytes": size,
                    "source_url": final_url,
                    "method": "browser_direct_stream",
                }

            html = page.content()
            page.close()
            ctx.close()

        pdf_link = _extract_pdf_link(url, html)
        if not pdf_link:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No PDF link found on page using browser automation. "
                    "The page may require interactive login/navigation."
                ),
            )

        size = _stream_to_disk(pdf_link, output_path)
        return {
            "path": str(output_path),
            "filename": output_path.name,
            "size_bytes": size,
            "source_url": pdf_link,
            "method": "browser_page_pdf_link",
        }

    except HTTPException:
        if output_path.exists():
            output_path.unlink()
        raise
    except PlaywrightError as exc:
        if output_path.exists():
            output_path.unlink()
        raise HTTPException(status_code=502, detail=f"Browser automation failed: {exc}") from exc
