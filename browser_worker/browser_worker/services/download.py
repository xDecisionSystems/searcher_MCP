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
from ..logger import log_event


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
    """Return the best PDF link found in static HTML, or None.

    Priority order:
    1. <a> whose href ends with .pdf
    2. <a> whose link text contains "pdf"
    3. <a> whose href contains "pdf"
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


def _click_pdf_button(page: Any, out_path: Path) -> tuple[int, str] | None:
    """Try to click a PDF download button and intercept the downloaded file.

    Works for JS-driven buttons (e.g. ScienceDirect "Download PDF") that do not
    have a plain href. Returns (size_bytes, source_url) on success, None if not found.
    """
    # Selectors tried in priority order
    selectors = [
        "a:has-text('Download PDF')",
        "a:has-text('View PDF')",
        "button:has-text('Download PDF')",
        "a[href*='pdf']:visible",
        "a:has-text('PDF')",
        "button:has-text('PDF')",
        "[data-testid*='pdf']",
        "[aria-label*='PDF']",
        "[aria-label*='pdf']",
    ]

    btn = None
    matched_selector = None
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=2000):
                btn = loc
                matched_selector = sel
                break
        except PlaywrightError:
            continue

    if btn is None:
        log_event("pdf_button_not_found", page_url=page.url, selectors_tried=selectors)
        return None

    log_event("pdf_button_found", selector=matched_selector, page_url=page.url)

    ctx = page.context
    captured_pdf_url: list[str] = []

    def _sniff_pdf(route: Any, request: Any) -> None:
        url = request.url
        if "pdf" in url.lower() or url.lower().endswith(".pdf"):
            if url not in captured_pdf_url:
                captured_pdf_url.append(url)
                log_event("pdf_url_sniffed", url=url)
        route.continue_()

    # Intercept all network requests on context to catch the PDF fetch from the viewer.
    try:
        ctx.route("**/*", _sniff_pdf)
    except PlaywrightError:
        pass

    download_obj = None
    popup_page = None

    # Watch for a direct download or a new tab simultaneously.
    try:
        with ctx.expect_page(timeout=20000) as popup_info:
            with page.expect_download(timeout=20000) as dl_info:
                btn.click()
            download_obj = dl_info.value
    except PlaywrightError:
        try:
            popup_page = popup_info.value
        except Exception:
            popup_page = None

    # Wait a moment for any in-flight PDF network requests to be sniffed.
    try:
        page.wait_for_timeout(3000)
    except PlaywrightError:
        pass

    try:
        ctx.unroute("**/*", _sniff_pdf)
    except PlaywrightError:
        pass

    # Strategy 1: direct browser download event.
    if download_obj is not None:
        try:
            download_obj.save_as(str(out_path))
            size = out_path.stat().st_size
            source = download_obj.url or page.url
            log_event("pdf_download_event", selector=matched_selector, size_bytes=size, source_url=source)
            return size, source
        except PlaywrightError as exc:
            log_event("pdf_download_event_failed", selector=matched_selector, error=str(exc))

    # Strategy 2: new tab/popup opened (PDF viewer in separate tab).
    if popup_page is not None:
        try:
            popup_page.wait_for_load_state("domcontentloaded", timeout=20000)
        except PlaywrightError:
            pass
        popup_url = popup_page.url
        log_event("pdf_popup_detected", popup_url=popup_url)
        result = _fetch_pdf_with_browser(popup_page, popup_url, out_path)
        try:
            popup_page.close()
        except PlaywrightError:
            pass
        if result is not None:
            return result

    # Strategy 3: PDF URL captured from network sniffing (in-page renderer like ScienceDirect).
    if captured_pdf_url:
        log_event("pdf_sniff_attempting", candidates=captured_pdf_url)
        for pdf_url in captured_pdf_url:
            result = _fetch_pdf_with_browser(page, pdf_url, out_path)
            if result is not None:
                return result

    # Strategy 4: check if current page navigated directly to a PDF.
    nav_url = page.url
    content_type = ""
    try:
        resp = page.request.get(nav_url, timeout=int(REQUEST_TIMEOUT * 1000))
        content_type = (resp.headers.get("content-type") or "").lower()
        log_event("pdf_nav_check", navigated_url=nav_url, content_type=content_type)
    except PlaywrightError as exc:
        log_event("pdf_nav_check_failed", navigated_url=nav_url, error=str(exc))

    if "pdf" in content_type or nav_url.lower().endswith(".pdf"):
        result = _fetch_pdf_with_browser(page, nav_url, out_path)
        if result is not None:
            return result

    log_event("pdf_nav_not_pdf", navigated_url=nav_url, content_type=content_type)
    return None


def _fetch_pdf_with_browser(page: Any, url: str, out_path: Path) -> tuple[int, str] | None:
    """Download a PDF using the browser session (carries cookies/auth), fall back to requests.

    Returns (size_bytes, source_url) on success, None on failure.
    """
    try:
        api_resp = page.request.get(url, timeout=int(REQUEST_TIMEOUT * 1000))
        if api_resp.ok:
            data = api_resp.body()
            max_bytes = MAX_DOWNLOAD_MB * 1024 * 1024
            if len(data) > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Download exceeded configured max size ({MAX_DOWNLOAD_MB} MB).",
                )
            out_path.write_bytes(data)
            log_event("pdf_browser_stream_ok", url=url, size_bytes=len(data))
            return len(data), url
        else:
            log_event("pdf_browser_stream_failed", url=url, http_status=api_resp.status)
    except HTTPException:
        raise
    except Exception as exc:
        log_event("pdf_browser_stream_error", url=url, error=str(exc))
    try:
        size = _stream_to_disk(url, out_path)
        log_event("pdf_plain_stream_ok", url=url, size_bytes=size)
        return size, url
    except Exception as exc:
        log_event("pdf_plain_stream_error", url=url, error=str(exc))
    return None


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


def _close_context_if_needed(ctx: Any) -> None:
    """Close context only for local launches; keep shared CDP context alive."""
    from ..config import CDP_URL

    if CDP_URL:
        return
    ctx.close()


def _navigate_for_analysis(page: Any, url: str) -> tuple[Any | None, str, str]:
    """Navigate to URL and return response, final URL, and HTML snapshot.

    Some auth handoff flows (for example EZproxy) can raise ERR_ABORTED while
    still landing the browser on a useful login URL. Treat that case as
    recoverable so callers can decide whether to prompt for login.
    """
    aborted = False
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=int(REQUEST_TIMEOUT * 1000))
    except PlaywrightError as exc:
        if "ERR_ABORTED" not in str(exc):
            raise
        response = None
        aborted = True

    try:
        current_url = page.url
    except PlaywrightError:
        current_url = url
    try:
        html = page.content()
    except PlaywrightError:
        html = ""

    # ERR_ABORTED on EZproxy/auth redirects: the page is in a broken state.
    # Signal login_required via synthetic HTML so callers detect it correctly.
    if aborted and not html:
        html = "<html><body><p>login</p><p>sign in</p></body></html>"

    return response, current_url, html


def _dismiss_cookie_banners(page: Any) -> None:
    """Click common 'reject optional cookies' / 'accept necessary only' buttons.

    Tries a prioritised list of selectors. Silently skips any that are absent or
    throw — the goal is best-effort dismissal, not a guarantee.
    """
    reject_selectors = [
        # Generic reject/necessary-only patterns
        "button:has-text('Reject all')",
        "button:has-text('Reject All')",
        "button:has-text('Decline all')",
        "button:has-text('Decline All')",
        "button:has-text('Only necessary')",
        "button:has-text('Only essential')",
        "button:has-text('Accept necessary')",
        "button:has-text('Accept only necessary')",
        "button:has-text('Accept necessary cookies')",
        "button:has-text('Necessary cookies only')",
        "button:has-text('Use necessary cookies only')",
        # Springer / Nature
        "button[data-test='reject-button']",
        "button#onetrust-reject-all-handler",
        # Elsevier / ScienceDirect
        "button.reject-btn",
        "button:has-text('Manage cookies')",  # skip — opens dialog
        # OneTrust (very common)
        "#onetrust-reject-all-handler",
        ".ot-sdk-btn-handler[id*='reject']",
        # Cookiebot
        "#CybotCookiebotDialogBodyButtonDecline",
        # Generic close
        "button[aria-label*='reject' i]",
        "button[aria-label*='decline' i]",
    ]
    for sel in reject_selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=1000):
                loc.click(timeout=3000)
                log_event("cookie_banner_dismissed", selector=sel)
                page.wait_for_timeout(500)
                return
        except PlaywrightError:
            continue


def _show_url_in_novnc(ctx: Any, url: str) -> Any:
    """Navigate the active noVNC tab to url so the user sees it immediately.

    Reuses the first existing page (already visible in noVNC) rather than
    opening a background tab that bring_to_front may fail to surface.
    Falls back to a new page if no existing pages are found.
    """
    pages = ctx.pages
    page = pages[0] if pages else ctx.new_page()
    try:
        page.bring_to_front()
    except PlaywrightError:
        pass
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except PlaywrightError:
        pass
    return page


def _is_login_page(html: str, url: str) -> bool:
    """Heuristic: returns True if the page looks like a login wall or bot challenge."""
    # Cloudflare challenge: 403 with challenge token in URL
    if "__cf_chl_rt_tk" in url or "cf-chl-bypass" in url:
        return True
    lower = html.lower()
    # Cloudflare challenge page signals
    if "checking if the site connection is secure" in lower or "enable javascript and cookies" in lower:
        return True
    login_signals = [
        "sign in", "log in", "login", "please sign", "access denied",
        "institutional access", "subscribe", "purchase access",
        "you need to", "register to", "create account",
    ]
    # Also check if we've been redirected to an auth domain
    auth_domains = ["login.", "accounts.", "auth.", "shibboleth.", "idp."]
    from urllib.parse import urlparse as _up
    domain = _up(url).netloc.lower()
    if any(d in domain for d in auth_domains):
        return True
    matched = sum(1 for s in login_signals if s in lower)
    return matched >= 2


def _login_required_response(requested_url: str, current_url: str) -> dict[str, Any]:
    from ..config import NOVNC_URL

    cloudflare = "__cf_chl_rt_tk" in current_url
    if cloudflare:
        message = "A Cloudflare CAPTCHA challenge was detected. Complete it in the browser to establish a trusted session."
        prompt = (
            f"A Cloudflare CAPTCHA has appeared in the browser at {NOVNC_URL} — "
            "please complete it there, then press **OK** to retry the download, "
            "or press **Stop** to cancel."
        )
    else:
        message = "Login is required to download this paper. The login page has been opened in the remote browser."
        prompt = (
            f"A login page has been opened in the browser at {NOVNC_URL} — "
            "please log in there, then press **OK** to retry the download, "
            "or press **Stop** to cancel."
        )

    return {
        "status": "login_required",
        "requires_login": True,
        "cloudflare_challenge": cloudflare,
        "message": message,
        "requested_url": requested_url,
        "current_url": current_url,
        "novnc_url": NOVNC_URL,
        "user_prompt": prompt,
        "retry_recommended": True,
        "method": "interactive_login_required",
    }



def download_paper_via_browser(url: str, filename: str | None = None) -> dict[str, Any]:
    _validate_http_url(url)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    base_name = filename.strip() if filename else _safe_filename(url)
    if not base_name.lower().endswith(".pdf"):
        base_name = f"{base_name}.pdf"
    base_name = re.sub(r"[^A-Za-z0-9._-]", "_", base_name)[:220]
    output_path = _unique_output_path(DOWNLOAD_DIR, base_name)

    log_event("download_start", url=url, output_path=str(output_path))

    try:
        with sync_playwright() as playwright:
            ctx = _get_browser_context(playwright)

            # Use the first existing page (already visible in noVNC) so every
            # navigation is visible to the user without needing bring_to_front.
            pages = ctx.pages
            page = pages[0] if pages else ctx.new_page()

            response, current_url, html = _navigate_for_analysis(page, url)
            content_type = ""
            if response is not None:
                content_type = (response.header_value("content-type") or "").lower()
            http_status = response.status if response is not None else None
            log_event("page_loaded", requested_url=url, final_url=current_url,
                      http_status=http_status, content_type=content_type)

            _dismiss_cookie_banners(page)

            if "pdf" in content_type:
                final_url = page.url
                _close_context_if_needed(ctx)
                size = _stream_to_disk(final_url, output_path)
                result = {
                    "path": str(output_path),
                    "filename": output_path.name,
                    "size_bytes": size,
                    "source_url": final_url,
                    "method": "browser_direct_stream",
                }
                log_event("download_success", **result)
                return result

            # Try clicking the PDF button before the login check — pages that are
            # fully authenticated (e.g. ScienceDirect) may still contain "sign in"
            # in their nav/footer, causing false-positive login detection.
            click_result = _click_pdf_button(page, output_path)
            if click_result is not None:
                size, pdf_source_url = click_result
                result = {
                    "path": str(output_path),
                    "filename": output_path.name,
                    "size_bytes": size,
                    "source_url": pdf_source_url,
                    "method": "browser_click_download",
                }
                log_event("download_success", **result)
                return result

            login_signals_matched = [
                s for s in [
                    "sign in", "log in", "login", "please sign", "access denied",
                    "institutional access", "subscribe", "purchase access",
                    "you need to", "register to", "create account",
                ]
                if s in html.lower()
            ]
            is_login = _is_login_page(html, current_url)
            log_event("login_check", url=current_url, is_login_page=is_login,
                      signals_matched=login_signals_matched)

            if is_login:
                if not html or html.strip() == "<html><body><p>login</p><p>sign in</p></body></html>":
                    _show_url_in_novnc(ctx, url)
                log_event("download_login_required", url=url, final_url=current_url)
                return _login_required_response(url, current_url)

            # Fall back to scraping a plain href PDF link.
            pdf_link = _extract_pdf_link(current_url, html)
            log_event("pdf_link_scrape", found=pdf_link is not None, link=pdf_link)
            if pdf_link:
                _close_context_if_needed(ctx)
                size = _stream_to_disk(pdf_link, output_path)
                result = {
                    "path": str(output_path),
                    "filename": output_path.name,
                    "size_bytes": size,
                    "source_url": pdf_link,
                    "method": "browser_page_pdf_link",
                }
                log_event("download_success", **result)
                return result

            _close_context_if_needed(ctx)
            log_event("download_failed", url=url, final_url=current_url,
                      reason="no_pdf_button_or_link")
            raise HTTPException(
                status_code=404,
                detail="No PDF button or link found. The page may require interactive login.",
            )

    except HTTPException:
        if output_path.exists():
            output_path.unlink()
        raise
    except PlaywrightError as exc:
        if output_path.exists():
            output_path.unlink()
        log_event("download_error", url=url, error=str(exc))
        raise HTTPException(status_code=502, detail=f"Browser automation failed: {exc}") from exc
