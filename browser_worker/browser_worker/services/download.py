import re
import threading
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from ..config import APP_USER_AGENT, DOWNLOAD_DIR, MAX_DOWNLOAD_MB, REQUEST_TIMEOUT
from ..logger import log_event
from .recorder import load_strategy

# ── Login detection defaults ───────────────────────────────────────────────────

_DEFAULT_LOGIN_SIGNALS = [
    "sign in", "log in", "login", "please sign", "access denied",
    "institutional access", "subscribe", "purchase access",
    "you need to", "register to", "create account",
]
_DEFAULT_AUTH_DOMAINS = ["login.", "accounts.", "auth.", "shibboleth.", "idp."]
_DEFAULT_LOGIN_THRESHOLD = 2

# ── No-access detection ────────────────────────────────────────────────────────

_DEFAULT_NO_ACCESS_SIGNALS = [
    "your institution has not purchased",
    "your institution does not have access",
    "institution does not have access",
    "not available to your institution",
    "please get in touch with your librarian",
    "recommend this title to your librarian",
    "purchase this content",
    "buy this article",
    "rent or buy",
    "full access isn't included in your subscription",
    "this article is not included",
    "no access",
    "access denied",
    "this content is not available",
    "you do not have access to this content",
    "full text access",
    "get access",
]

# ── Cookie banner selectors ────────────────────────────────────────────────────

_COOKIE_REJECT_SELECTORS = [
    "button:has-text('Reject all')",
    "button:has-text('Reject All')",
    "button:has-text('Decline all')",
    "button:has-text('Decline All')",
    "button:has-text('Deny')",
    "button:has-text('Only necessary')",
    "button:has-text('Only essential')",
    "button:has-text('Accept necessary')",
    "button:has-text('Accept only necessary')",
    "button:has-text('Accept necessary cookies')",
    "button:has-text('Necessary cookies only')",
    "button:has-text('Use necessary cookies only')",
    "button[data-test='reject-button']",
    "button#onetrust-reject-all-handler",
    "button.reject-btn",
    "#onetrust-reject-all-handler",
    ".ot-sdk-btn-handler[id*='reject']",
    "#CybotCookiebotDialogBodyButtonDecline",
    "button[aria-label*='reject' i]",
    "button[aria-label*='decline' i]",
    "button[aria-label*='deny' i]",
]

# ── Generic PDF button selectors (fallback when no strategy exists) ────────────

_PDF_BUTTON_SELECTORS = [
    "a:has-text('Download PDF')",
    "a:has-text('View PDF')",
    "a:has-text('Download full text')",
    "a:has-text('Full text PDF')",
    "button:has-text('Download PDF')",
    "button:has-text('PDF')",
    "[data-testid*='pdf']",
    "[aria-label*='PDF']",
    "[aria-label*='pdf']",
    "a:has-text('PDF')",
]

_PDF_DROPDOWN_SELECTORS = [
    "button:has-text('Download')",
    "a:has-text('Download')",
    "button[aria-haspopup='true']:has-text('Download')",
    "button[aria-expanded='false']:has-text('Download')",
    ".dropdown-toggle:has-text('Download')",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _validate_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid URL. Use http(s) URL.")


def _safe_filename(url: str, fallback_prefix: str = "paper") -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name.strip() or f"{fallback_prefix}-{uuid.uuid4().hex}.pdf"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:220]


def _unique_output_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
    return directory / f"{stem}-{uuid.uuid4().hex[:8]}.pdf"


def _stream_to_disk(url: str, out_path: Path) -> int:
    """Stream url to disk via plain requests. Raises HTTPException on failure."""
    max_bytes = MAX_DOWNLOAD_MB * 1024 * 1024
    size = 0
    try:
        with requests.get(
            url, stream=True, timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": APP_USER_AGENT}, allow_redirects=True,
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
                            detail=f"Download exceeded {MAX_DOWNLOAD_MB} MB limit.",
                        )
                    fh.write(chunk)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Download request failed: {exc}") from exc
    return size


def _extract_pdf_link(base_url: str, html: str) -> str | None:
    """Return the best PDF href found in static HTML, or None."""
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[int, str]] = []
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href", "")).strip()
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            continue
        absolute = urljoin(base_url, href)
        if urlparse(absolute).scheme not in {"http", "https"}:
            continue
        text = anchor.get_text(" ", strip=True).lower()
        if href.lower().endswith(".pdf"):
            candidates.append((0, absolute))
        elif "pdf" in text:
            candidates.append((1, absolute))
        elif "pdf" in href.lower():
            candidates.append((2, absolute))
    if not candidates:
        return None
    return sorted(candidates)[0][1]


def _is_login_page(html: str, url: str, login_detection: dict[str, Any] | None = None) -> bool:
    """Return True if the page looks like a login wall or bot challenge."""
    # Cloudflare always checked regardless of strategy config.
    if "__cf_chl_rt_tk" in url or "cf-chl-bypass" in url:
        return True
    lower = html.lower()
    if "checking if the site connection is secure" in lower or "enable javascript and cookies" in lower:
        return True

    if login_detection is not None and not login_detection.get("enabled", True):
        return False

    signals = _DEFAULT_LOGIN_SIGNALS
    auth_domains = _DEFAULT_AUTH_DOMAINS
    threshold = _DEFAULT_LOGIN_THRESHOLD
    if login_detection is not None:
        signals = login_detection.get("signals", signals)
        auth_domains = login_detection.get("auth_domains", auth_domains)
        threshold = login_detection.get("threshold", threshold)

    if any(d in urlparse(url).netloc.lower() for d in auth_domains):
        return True
    return sum(1 for s in signals if s in lower) >= threshold


def _is_no_access_page(html: str, strategy: dict[str, Any] | None = None) -> bool:
    """Return True if the page indicates this specific paper is paywalled."""
    lower = html.lower()
    signals = _DEFAULT_NO_ACCESS_SIGNALS
    if strategy is not None:
        extra = strategy.get("no_access_signals", [])
        if extra:
            signals = signals + [s.lower() for s in extra]
    return any(s in lower for s in signals)


def _no_strategy_hint(domain: str, url: str) -> str:
    return (
        f"No recorded strategy exists for '{domain}'. "
        f"Tell the user: \"No download strategy exists for {domain}. "
        f"To create one, call POST /record_session?url={url}, "
        f"manually download a PDF in the noVNC browser, then call POST /stop_recording. "
        f"Future downloads from {domain} will use the recorded steps automatically.\""
    )


def _login_required_response(
    requested_url: str, current_url: str, strategy: dict[str, Any] | None = None
) -> dict[str, Any]:
    from ..config import NOVNC_URL

    cloudflare = "__cf_chl_rt_tk" in current_url
    if cloudflare:
        message = "A Cloudflare CAPTCHA challenge was detected."
        prompt = (
            f"A Cloudflare CAPTCHA has appeared in the browser at {NOVNC_URL} — "
            "please complete it there, then press **OK** to retry or **Stop** to cancel."
        )
    else:
        message = "Login is required to download this paper."
        prompt = (
            f"A login page has been opened in the browser at {NOVNC_URL} — "
            "please log in there, then press **OK** to retry or **Stop** to cancel."
        )

    resp: dict[str, Any] = {
        "status": "login_required",
        "requires_login": True,
        "cloudflare_challenge": cloudflare,
        "message": message,
        "requested_url": requested_url,
        "current_url": current_url,
        "novnc_url": NOVNC_URL,
        "user_prompt": prompt,
        "retry_recommended": True,
    }
    if strategy is None:
        domain = urlparse(requested_url).netloc.lower()
        resp["strategy_hint"] = _no_strategy_hint(domain, requested_url)
    return resp


# ── Browser context ────────────────────────────────────────────────────────────

def _get_browser_context(playwright: Any) -> Any:
    from ..config import CDP_URL, HEADLESS, SESSION_DIR

    if CDP_URL:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        contexts = browser.contexts
        return contexts[0] if contexts else browser.new_context(user_agent=APP_USER_AGENT)

    if SESSION_DIR is not None:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        return playwright.chromium.launch_persistent_context(
            str(SESSION_DIR), headless=HEADLESS, user_agent=APP_USER_AGENT,
        )

    return playwright.chromium.launch(headless=HEADLESS).new_context(user_agent=APP_USER_AGENT)


def _close_context_if_needed(ctx: Any) -> None:
    from ..config import CDP_URL
    if not CDP_URL:
        try:
            ctx.close()
        except PlaywrightError:
            pass


# ── Page helpers ───────────────────────────────────────────────────────────────

def _navigate(page: Any, url: str) -> tuple[Any | None, str, str]:
    """Navigate to url. Returns (response, final_url, html).

    Returns sentinel html '__AUTO_DOWNLOAD__' if the navigation triggered a
    browser file download instead of a page load.
    """
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=int(REQUEST_TIMEOUT * 1000))
        return response, page.url, page.content()
    except PlaywrightError as exc:
        err = str(exc)
        if "Download is starting" in err:
            return None, url, "__AUTO_DOWNLOAD__"
        if "ERR_ABORTED" in err:
            # EZproxy / auth redirect landed somewhere — return synthetic login signal.
            return None, page.url, "<html><body><p>login</p><p>sign in</p></body></html>"
        raise


def _dismiss_cookie_banners(page: Any) -> None:
    for sel in _COOKIE_REJECT_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=300):
                loc.click(timeout=2000)
                log_event("cookie_banner_dismissed", selector=sel)
                page.wait_for_timeout(800)
                return
        except PlaywrightError:
            continue


def _click_element(page: Any, selector: str, out_path: Path) -> dict[str, Any] | None:
    """Find selector, navigate its href or click it, intercept any download event.

    Returns a result dict on success, None if element not found or download failed.
    """
    try:
        page.wait_for_selector(selector, state="attached", timeout=3000)
    except PlaywrightError:
        log_event("element_not_found", selector=selector)
        return None

    loc = page.locator(selector).first
    href = loc.get_attribute("href") or ""
    abs_href = urljoin(page.url, href) if href else ""

    try:
        with page.expect_download(timeout=int(REQUEST_TIMEOUT * 1000)) as dl_info:
            if abs_href:
                page.goto(abs_href, wait_until="domcontentloaded",
                          timeout=int(REQUEST_TIMEOUT * 1000))
            else:
                loc.click(force=True, timeout=5000)
        dl = dl_info.value
        dl.save_as(str(out_path))
        size = out_path.stat().st_size
        log_event("download_event_captured", selector=selector, url=dl.url, size_bytes=size)
        return {
            "path": str(out_path),
            "filename": out_path.name,
            "size_bytes": size,
            "source_url": dl.url,
            "method": "browser_download_event",
        }
    except PlaywrightError:
        # No download event — navigation completed normally.
        pass

    return None


def _find_and_click_pdf_button(page: Any, out_path: Path) -> dict[str, Any] | None:
    """Generic fallback: try dropdown openers then common PDF button selectors."""
    # Try opening dropdowns first.
    for sel in _PDF_DROPDOWN_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=300):
                loc.click(timeout=2000)
                page.wait_for_timeout(500)
                log_event("dropdown_opened", selector=sel)
                break
        except PlaywrightError:
            continue

    for sel in _PDF_BUTTON_SELECTORS:
        try:
            loc = page.locator(sel).first
            if not (loc.count() and loc.is_visible(timeout=300)):
                continue
        except PlaywrightError:
            continue

        log_event("pdf_button_found", selector=sel, page_url=page.url)
        result = _click_element(page, sel, out_path)
        if result is not None:
            return result

        # Button found but no download event — try sniffing the PDF URL via routing.
        ctx = page.context
        sniffed: list[str] = []
        urls_before = {p.url for p in ctx.pages}

        def _sniff(route: Any, request: Any) -> None:
            u = request.url
            if ("pdf" in u.lower() or u.lower().endswith(".pdf")) and u not in urls_before:
                sniffed.append(u)
                log_event("pdf_url_sniffed", url=u)
            route.continue_()

        try:
            ctx.route("**/*", _sniff)
            loc.click(timeout=5000)
            page.wait_for_timeout(3000)
        except PlaywrightError:
            pass
        finally:
            try:
                ctx.unroute("**/*", _sniff)
            except PlaywrightError:
                pass

        for pdf_url in sniffed:
            try:
                size = _stream_to_disk(pdf_url, out_path)
                log_event("pdf_sniff_stream_ok", url=pdf_url, size_bytes=size)
                return {
                    "path": str(out_path),
                    "filename": out_path.name,
                    "size_bytes": size,
                    "source_url": pdf_url,
                    "method": "browser_sniff_stream",
                }
            except HTTPException:
                continue

    log_event("pdf_button_not_found", page_url=page.url)
    return None


# ── Strategy replay ────────────────────────────────────────────────────────────

def _replay_strategy(page: Any, strategy: dict[str, Any], out_path: Path) -> dict[str, Any] | None:
    """Replay recorded strategy steps. Returns result dict or None."""
    steps: list[dict[str, Any]] = strategy.get("steps", [])
    domain = strategy.get("domain", "")
    log_event("strategy_replay_start", domain=domain, steps=len(steps))

    # Context-level listener survives page navigations.
    captured_pdf: list[tuple[str, bytes]] = []

    def on_response(response: Any) -> None:
        try:
            ct = (response.headers.get("content-type") or "").lower()
            url = response.url
            url_lower = url.lower()
            is_pdf = (
                "pdf" in ct
                or url_lower.endswith(".pdf")
                or ("sciencedirectassets.com" in url_lower and "main.pdf" in url_lower)
            )
            if is_pdf:
                data = response.body()
                if data and len(data) > 10000:
                    captured_pdf.append((url, data))
                    log_event("strategy_pdf_captured", url=url, size=len(data))
        except Exception:
            pass

    ctx = page.context
    ctx.on("response", on_response)

    try:
        # Wait for JS to settle before replaying clicks.
        for state in ("load", "networkidle"):
            try:
                page.wait_for_load_state(state, timeout=5000)
            except PlaywrightError:
                pass

        for step in steps:
            step_type = step.get("type")

            if step_type == "navigate":
                continue

            elif step_type == "click":
                selector = step.get("selector", "")
                if not selector:
                    continue
                result = _click_element(page, selector, out_path)
                if result is not None:
                    log_event("strategy_replay_success", method=result["method"])
                    return result
                # No download event — navigation happened, on_response may have captured PDF.
                if captured_pdf:
                    break

            elif step_type == "wait_for_pdf_response":
                deadline = REQUEST_TIMEOUT
                waited = 0.0
                while waited < deadline and not captured_pdf:
                    page.wait_for_timeout(500)
                    waited += 0.5
                if captured_pdf:
                    break

        if captured_pdf:
            pdf_url, data = captured_pdf[0]
            max_bytes = MAX_DOWNLOAD_MB * 1024 * 1024
            if len(data) > max_bytes:
                raise HTTPException(status_code=413, detail=f"Download exceeded {MAX_DOWNLOAD_MB} MB limit.")
            out_path.write_bytes(data)
            log_event("strategy_replay_success", url=pdf_url, size=len(data))
            return {
                "path": str(out_path),
                "filename": out_path.name,
                "size_bytes": len(data),
                "source_url": pdf_url,
                "method": "strategy_response_capture",
            }

        log_event("strategy_replay_failed", domain=domain)
        return None

    finally:
        try:
            ctx.remove_listener("response", on_response)
        except Exception:
            pass


# ── Post-processing ────────────────────────────────────────────────────────────

def _apply_post_processing(path: Path, post_process: dict[str, Any]) -> None:
    """Apply post-processing steps defined in a strategy's post_process block."""
    strip_first = post_process.get("strip_first_pages", 0)
    strip_last = post_process.get("strip_last_pages", 0)
    if not strip_first and not strip_last:
        return
    try:
        from pypdf import PdfReader, PdfWriter  # noqa: PLC0415
    except ImportError:
        log_event("post_process_skip", reason="pypdf not installed")
        return

    reader = PdfReader(str(path))
    total = len(reader.pages)
    start = min(strip_first, total)
    end = max(0, total - strip_last)
    if start >= end:
        log_event("post_process_skip", reason="nothing left after stripping", total=total)
        return

    writer = PdfWriter()
    for i in range(start, end):
        writer.add_page(reader.pages[i])

    tmp = path.with_suffix(".tmp.pdf")
    with open(tmp, "wb") as fh:
        writer.write(fh)
    tmp.replace(path)
    log_event("post_process_strip", strip_first=strip_first, strip_last=strip_last,
              original_pages=total, remaining_pages=end - start)


# ── EBSCO browser search ──────────────────────────────────────────────────────

def _ebsco_ensure_signed_in(page: Any, wait_for_selector: str | None = None) -> None:
    """If EBSCO shows a guest banner, click Sign in to establish institutional session."""
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightError:
        pass
    html = page.content()
    if "Sign in to your institution" in html or "Welcome, Guest" in html:
        log_event("ebsco_guest_banner_detected")
        try:
            page.get_by_role("button", name="Sign in").or_(page.get_by_role("link", name="Sign in")).first.click(timeout=5000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightError:
                pass
            page.wait_for_timeout(2000)
            log_event("ebsco_signed_in", url=page.url)
            # Wait for a specific element to confirm the page is ready post sign-in.
            if wait_for_selector:
                try:
                    page.wait_for_selector(wait_for_selector, timeout=10000)
                except PlaywrightError:
                    pass
        except PlaywrightError as exc:
            log_event("ebsco_sign_in_failed", error=str(exc))


def download_ebsco_paper(url: str) -> dict:
    """Download a single paper from an EBSCO detail page URL.

    Navigates to the detail page, handles institutional sign-in if needed,
    clicks Download (twice — first opens a popup, second confirms), then
    captures the PDF from the API response.
    """
    from ..config import DOWNLOAD_DIR, MAX_DOWNLOAD_MB

    _validate_http_url(url)
    filename = f"ebsco-{uuid.uuid4().hex[:12]}.pdf"
    out_path = DOWNLOAD_DIR / filename

    log_event("ebsco_download_start", url=url)

    try:
        with sync_playwright() as playwright:
            ctx = _get_browser_context(playwright)
            pages = ctx.pages
            page = pages[0] if pages else ctx.new_page()

            captured_pdf: list[tuple[str, bytes]] = []

            def on_response(response: Any) -> None:
                try:
                    ct = (response.headers.get("content-type") or "").lower()
                    ru = response.url
                    if "pdf" in ct or ru.lower().endswith(".pdf"):
                        data = response.body()
                        if data and len(data) > 10000:
                            captured_pdf.append((ru, data))
                            log_event("ebsco_pdf_captured", url=ru, size=len(data))
                except Exception:
                    pass

            ctx.on("response", on_response)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)

                # Handle guest banner / institutional sign-in, wait for Download button.
                _ebsco_ensure_signed_in(page, wait_for_selector="button[data-auto='card-call-to-action-download-button']")

                # Wait for detail content to render after sign-in.
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except PlaywrightError:
                    pass
                page.wait_for_timeout(1500)

                # First click opens the download popup.
                try:
                    page.locator("button[data-auto='card-call-to-action-download-button']").first.click(timeout=10000)
                    log_event("ebsco_download_click1")
                except PlaywrightError as exc:
                    log_event("ebsco_download_click1_failed", error=str(exc))

                # Wait for the modal URL to load (click1 navigates to ?modal=details-bulk-download).
                try:
                    page.wait_for_url("**/search/details/**modal=details-bulk-download**", timeout=8000)
                    log_event("ebsco_modal_url_detected", url=page.url)
                except PlaywrightError:
                    log_event("ebsco_modal_url_wait_timeout", url=page.url)

                # Click the Download button inside the modal (bottom-right submit button, not the title).
                try:
                    page.wait_for_timeout(1000)
                    # Target the submit Download button — use last() since the modal title "Download" may also match text.
                    download_btn = page.get_by_role("button", name="Download").last
                    download_btn.wait_for(state="visible", timeout=8000)
                    download_btn.scroll_into_view_if_needed()
                    download_btn.click(timeout=8000)
                    log_event("ebsco_download_click2")
                except PlaywrightError as exc:
                    log_event("ebsco_download_click2_failed", error=str(exc))

                # Wait for PDF response to be captured.
                deadline = 30.0
                waited = 0.0
                while waited < deadline and not captured_pdf:
                    page.wait_for_timeout(500)
                    waited += 0.5

            finally:
                try:
                    ctx.remove_listener("response", on_response)
                except Exception:
                    pass
                _close_context_if_needed(ctx)

    except PlaywrightError as exc:
        raise HTTPException(status_code=502, detail=f"EBSCO download failed: {exc}") from exc

    if not captured_pdf:
        raise HTTPException(status_code=502, detail="No PDF captured from EBSCO detail page.")

    pdf_url, data = captured_pdf[0]
    max_bytes = MAX_DOWNLOAD_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Download exceeded {MAX_DOWNLOAD_MB} MB limit.")
    out_path.write_bytes(data)
    log_event("ebsco_download_done", url=pdf_url, size=len(data), path=str(out_path))
    return {
        "status": "downloaded",
        "filename": out_path.name,
        "size_bytes": len(data),
        "source_url": pdf_url,
        "local_path": str(out_path),
    }


def search_ebsco_via_browser(
    query: str,
    limit: int,
    year_low: int | None = None,
    year_high: int | None = None,
    page_delay_seconds: float = 2.0,
) -> dict:
    """Search EBSCO Research via the real Chromium browser.

    Navigates to the search results page, waits for the React SPA to finish
    loading, collects HTML, then clicks "Show more results" until limit items
    are collected or the button disappears. Returns raw HTML per snapshot for
    the caller to parse.
    """
    from urllib.parse import quote_plus
    from ..config import EBSCO_OPID

    limiters = ["FT:Y", "FT1:Y"]
    if year_low or year_high:
        lo = f"{year_low}-01-01" if year_low else ""
        hi = f"{year_high}-12-31" if year_high else ""
        limiters.append(f"DT1:{lo}/{hi}")

    params = (
        f"q={quote_plus(query)}"
        f"&autocorrect=y&expanders=concept&searchMode=all&searchSegment=all-results"
        f"&limiters={quote_plus(','.join(limiters))}"
    )
    search_url = f"https://research.ebsco.com/c/{EBSCO_OPID}/search/results?{params}"

    log_event("ebsco_search_start", query=query, limit=limit, url=search_url)

    pages_html: list[str] = []
    collected = 0

    try:
        with sync_playwright() as playwright:
            ctx = _get_browser_context(playwright)
            pages = ctx.pages
            page = pages[0] if pages else ctx.new_page()

            # Navigate to the search results page.
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightError:
                pass
            page.wait_for_timeout(1500)

            # If EBSCO shows a guest session, click the "Sign in" button to
            # establish the institutional session before results will load.
            html_check = page.content()
            if "Sign in to your institution" in html_check or "Welcome, Guest" in html_check:
                log_event("ebsco_guest_banner_detected")
                try:
                    page.get_by_role("button", name="Sign in").or_(page.get_by_role("link", name="Sign in")).first.click(timeout=5000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except PlaywrightError:
                        pass
                    page.wait_for_timeout(2000)
                    log_event("ebsco_signed_in", url=page.url)
                except PlaywrightError as exc:
                    log_event("ebsco_sign_in_failed", error=str(exc))
                    # Sign-in click failed — session may still be valid, continue.

            # Wait for results to finish loading after sign-in redirect.
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightError:
                pass
            page.wait_for_timeout(1500)

            # Drag the right-side scrollbar to the bottom to trigger EBSCO's
            # scroll listener and ensure the first batch of results renders.
            viewport = page.viewport_size or {"width": 1280, "height": 720}
            sb_x = viewport["width"] - 8
            sb_top = 60
            sb_bottom = viewport["height"] - 10
            page.mouse.move(sb_x, sb_top)
            page.mouse.down()
            for i in range(1, 11):
                page.mouse.move(sb_x, sb_top + (sb_bottom - sb_top) * i // 10)
                page.wait_for_timeout(100)
            page.mouse.up()
            page.wait_for_timeout(1500)

            result_selector = "[data-auto='search-result-item']"
            log_event("ebsco_page_ready", count=page.locator(result_selector).count())

            while True:
                collected = page.locator(result_selector).count()
                log_event("ebsco_page_collected", collected=collected)

                if collected >= limit:
                    break

                # Scroll to and click "Show more results", then scroll to bottom
                # again so the next batch renders before we check the count.
                show_more = page.locator("[data-auto='show-more-button']").first
                if not show_more.count():
                    log_event("ebsco_no_show_more", collected=collected)
                    break

                show_more.scroll_into_view_if_needed()
                show_more.click()
                page.wait_for_timeout(int(page_delay_seconds * 1000))

                # Scroll to bottom again after click to trigger next batch load.
                page.mouse.move(sb_x, sb_top)
                page.mouse.down()
                for i in range(1, 11):
                    page.mouse.move(sb_x, sb_top + (sb_bottom - sb_top) * i // 10)
                    page.wait_for_timeout(100)
                page.mouse.up()
                page.wait_for_timeout(1000)

            # Take a single snapshot after all items are loaded.
            html = page.content()
            pages_html.append(html)

            _close_context_if_needed(ctx)

    except PlaywrightError as exc:
        raise HTTPException(status_code=502, detail=f"EBSCO browser search failed: {exc}") from exc

    log_event("ebsco_search_done", snapshots=len(pages_html), collected=collected)
    return {"pages_html": pages_html, "page_count": len(pages_html)}


# ── Google Scholar browser search ─────────────────────────────────────────────

def search_google_scholar_via_browser(
    query: str,
    limit: int,
    start_index: int = 0,
    year_low: int | None = None,
    year_high: int | None = None,
    page_delay_seconds: float = 1.0,
) -> dict:
    """Search Google Scholar in the real Chromium browser, paginating via Next button.

    Navigates to the first results page, collects HTML, clicks the Next button,
    waits page_delay_seconds, then repeats until limit results are collected or
    no Next button is found. Returns raw HTML per page for the caller to parse.
    """
    from urllib.parse import quote_plus

    params = f"q={quote_plus(query)}&hl=en"
    if start_index:
        params += f"&start={start_index}"
    if year_low:
        params += f"&as_ylo={year_low}"
    if year_high:
        params += f"&as_yhi={year_high}"
    first_url = f"https://scholar.google.com/scholar?{params}"

    log_event("scholar_search_start", query=query, limit=limit, url=first_url)

    pages_html: list[str] = []
    try:
        with sync_playwright() as playwright:
            ctx = _get_browser_context(playwright)
            pages = ctx.pages
            page = pages[0] if pages else ctx.new_page()

            # Navigate to first page and wait for results to load.
            page.goto(first_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)

            collected = 0
            while collected < limit:
                html = page.content()
                pages_html.append(html)
                log_event("scholar_page_collected", page_num=len(pages_html), html_len=len(html))

                # Count results on this page (rough estimate — caller will parse exactly).
                collected += html.count('class="gs_r gs_or gs_scl"')

                if collected >= limit:
                    break

                # Scroll to bottom so Scholar renders the pagination bar.
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(500)

                # Find the Next link: Scholar renders it as <a href="..."><b>Next</b></a>.
                # Use Playwright locator to find by text content rather than CSS :has().
                next_link = None
                for a in page.query_selector_all("a"):
                    try:
                        if "Next" in (a.inner_text() or ""):
                            next_link = a
                            break
                    except PlaywrightError:
                        continue
                if not next_link:
                    log_event("scholar_no_next_page", page_num=len(pages_html))
                    break

                next_link.click()
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                page.wait_for_timeout(int(page_delay_seconds * 1000))

            _close_context_if_needed(ctx)

    except PlaywrightError as exc:
        raise HTTPException(status_code=502, detail=f"Scholar browser search failed: {exc}") from exc

    log_event("scholar_search_done", pages=len(pages_html), estimated_results=collected)
    return {"pages_html": pages_html, "page_count": len(pages_html)}


def search_web_of_science_via_browser(
    query: str,
    limit: int,
    year_low: int | None = None,
    year_high: int | None = None,
    page_delay_seconds: float = 2.0,
) -> dict:
    """Search Web of Science via the real Chromium browser.

    Types the query into the WoS smart-search box, clicks the search icon,
    waits for the Angular SPA to navigate to the summary/ results URL, then
    paginates via Next until limit results are collected.
    Returns raw HTML per page for the caller to parse.
    """
    log_event("wos_search_start", query=query, limit=limit)

    pages_html: list[str] = []
    collected = 0
    result_selector = "app-summary-title"

    try:
        with sync_playwright() as playwright:
            ctx = _get_browser_context(playwright)
            pages = ctx.pages
            page = pages[0] if pages else ctx.new_page()

            # Navigate to smart search.
            page.goto("https://www.webofscience.com/wos/woscc/smart-search", wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightError:
                pass
            page.wait_for_timeout(2000)

            # Find and fill the search textarea (WoS smart search uses a textarea).
            search_box = page.locator("textarea, input[type='text']:not([name='startDate']):not([name='endDate'])").first
            search_box.wait_for(state="visible", timeout=10000)
            search_box.click()
            search_box.fill(query)
            page.wait_for_timeout(500)

            # Click the purple search icon button to the right of the input.
            page.keyboard.press("Enter")

            # Wait for navigation to the summary results URL.
            try:
                page.wait_for_url("**/wos/woscc/summary/**", timeout=20000)
                log_event("wos_summary_url", url=page.url)
            except PlaywrightError:
                log_event("wos_summary_url_timeout", url=page.url)

            # Wait for Angular to render result cards.
            try:
                page.wait_for_selector(result_selector, timeout=20000)
            except PlaywrightError:
                log_event("wos_results_selector_timeout")
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightError:
                pass
            page.wait_for_timeout(1500)

            while collected < limit:
                html = page.content()
                pages_html.append(html)
                collected += html.count("<app-summary-title")
                log_event("wos_page_collected", page_num=len(pages_html), estimated=collected)

                if collected >= limit:
                    break

                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(500)

                next_btn = page.locator("button[aria-label='Next page'], [data-ta='next-page-button']").first
                try:
                    next_btn.wait_for(state="visible", timeout=3000)
                    if not next_btn.is_enabled():
                        log_event("wos_next_disabled", page_num=len(pages_html))
                        break
                    next_btn.click()
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except PlaywrightError:
                        pass
                    page.wait_for_timeout(int(page_delay_seconds * 1000))
                except PlaywrightError:
                    log_event("wos_no_next_page", page_num=len(pages_html))
                    break

            _close_context_if_needed(ctx)

    except PlaywrightError as exc:
        raise HTTPException(status_code=502, detail=f"Web of Science browser search failed: {exc}") from exc

    log_event("wos_search_done", pages=len(pages_html), estimated_results=collected)
    return {"pages_html": pages_html, "page_count": len(pages_html)}


# ── Generic page fetch ─────────────────────────────────────────────────────────

def fetch_page_via_browser(url: str) -> dict[str, Any]:
    """Navigate to url in the real Chromium instance and return the rendered HTML.

    Uses the same persistent browser context as download_paper_via_browser, so any
    session cookies (e.g. a solved Google Scholar CAPTCHA) are shared automatically.
    """
    _validate_http_url(url)
    log_event("fetch_page_start", url=url)

    try:
        with sync_playwright() as playwright:
            ctx = _get_browser_context(playwright)
            pages = ctx.pages
            page = pages[0] if pages else ctx.new_page()

            response, final_url, html = _navigate(page, url)

            status = response.status if response is not None else None
            log_event("fetch_page_done", url=url, final_url=final_url, http_status=status)
            _close_context_if_needed(ctx)

        return {"url": final_url, "status": status, "html": html}

    except PlaywrightError as exc:
        raise HTTPException(status_code=502, detail=f"Browser fetch failed: {exc}") from exc


# ── Download lock (one at a time) ─────────────────────────────────────────────

_download_lock = threading.Lock()


# ── Main entry point ───────────────────────────────────────────────────────────

def download_paper_via_browser(url: str, filename: str | None = None) -> dict[str, Any]:
    _validate_http_url(url)

    if not _download_lock.acquire(blocking=False):
        log_event("download_busy", url=url)
        raise HTTPException(
            status_code=409,
            detail={
                "status": "busy",
                "message": (
                    "A download is already in progress. "
                    "Wait for it to complete (or resolve any login/CAPTCHA prompt) "
                    "before starting another download."
                ),
                "requested_url": url,
            },
        )

    try:
        return _download_paper_locked(url=url, filename=filename)
    finally:
        _download_lock.release()


def _download_paper_locked(url: str, filename: str | None = None) -> dict[str, Any]:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    base_name = filename.strip() if filename else _safe_filename(url)
    if not base_name.lower().endswith(".pdf"):
        base_name = f"{base_name}.pdf"
    base_name = re.sub(r"[^A-Za-z0-9._-]", "_", base_name)[:220]
    out_path = _unique_output_path(DOWNLOAD_DIR, base_name)

    log_event("download_start", url=url, output_path=str(out_path))

    try:
        with sync_playwright() as playwright:
            ctx = _get_browser_context(playwright)

            # Open a fresh tab for this download so it is visible in noVNC and
            # isolated from other concurrent requests. The tab is always closed
            # when the download finishes (success, login wall, or failure).
            page = ctx.new_page()
            try:
                response, current_url, html = _navigate(page, url)

                if html == "__AUTO_DOWNLOAD__":
                    log_event("auto_download_detected", url=url)
                    result = _click_element(page, "body", out_path)
                    if result is None:
                        raise HTTPException(status_code=502, detail="Auto-download triggered but could not be captured.")
                    log_event("download_success", **result)
                    return result

                content_type = ""
                if response is not None:
                    content_type = (response.header_value("content-type") or "").lower()
                log_event("page_loaded", requested_url=url, final_url=current_url,
                          http_status=response.status if response else None,
                          content_type=content_type)

                _dismiss_cookie_banners(page)

                # Direct PDF response — stream it.
                if "pdf" in content_type:
                    _stream_to_disk(page.url, out_path)
                    nav_domain = urlparse(current_url).netloc.lower().split(":")[0]
                    strategy = load_strategy(nav_domain) or load_strategy(
                        urlparse(url).netloc.lower().split(":")[0]
                    )
                    post_process = strategy.get("post_process", {}) if strategy else {}
                    _apply_post_processing(out_path, post_process)
                    result = {
                        "path": str(out_path), "filename": out_path.name,
                        "size_bytes": out_path.stat().st_size, "source_url": page.url,
                        "method": "direct_pdf_stream",
                    }
                    log_event("download_success", **result)
                    return result

                # Load strategy for this domain.
                nav_domain = urlparse(current_url).netloc.lower().split(":")[0]
                strategy = load_strategy(nav_domain) or load_strategy(
                    urlparse(url).netloc.lower().split(":")[0]
                )
                login_detection = strategy.get("login_detection") if strategy else None
                post_process = strategy.get("post_process", {}) if strategy else {}

                # Inaccessible domain — return early with clear message.
                if strategy is not None and not strategy.get("accessible", True):
                    log_event("download_inaccessible", domain=nav_domain, url=url)
                    return {
                        "status": "inaccessible",
                        "message": strategy.get("inaccessible_reason", f"No institutional access to {nav_domain}."),
                        "requested_url": url,
                        "domain": nav_domain,
                    }

                # Strategy replay.
                if strategy is not None:
                    log_event("strategy_found", domain=nav_domain, steps=len(strategy.get("steps", [])))
                    result = _replay_strategy(page, strategy, out_path)
                    if result is not None:
                        _apply_post_processing(out_path, post_process)
                        result["size_bytes"] = out_path.stat().st_size
                        log_event("download_success", **result)
                        return result
                    log_event("strategy_replay_no_result", domain=nav_domain)

                # Generic PDF button fallback.
                result = _find_and_click_pdf_button(page, out_path)
                if result is not None:
                    _apply_post_processing(out_path, post_process)
                    result["size_bytes"] = out_path.stat().st_size
                    log_event("download_success", **result)
                    return result

                # No-access check — specific paper/book not covered by institution.
                current_html = page.content()
                if _is_no_access_page(current_html, strategy):
                    log_event("download_no_access", url=url, domain=nav_domain)
                    _close_context_if_needed(ctx)
                    return {
                        "status": "no_access",
                        "message": (
                            f"Your institution does not have access to this specific paper on {nav_domain}. "
                            "Try finding a preprint on arxiv.org, the author's institutional page, "
                            "or request via interlibrary loan."
                        ),
                        "requested_url": url,
                        "domain": nav_domain,
                    }

                # Login check.
                is_login = _is_login_page(html, current_url, login_detection=login_detection)
                log_event("login_check", url=current_url, is_login_page=is_login)
                if is_login:
                    if not html.strip() or "login" in html and len(html) < 200:
                        try:
                            page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        except PlaywrightError:
                            pass
                    log_event("download_login_required", url=url, final_url=current_url)
                    return _login_required_response(url, current_url, strategy=strategy)

                # Static href scrape.
                pdf_link = _extract_pdf_link(current_url, html)
                log_event("pdf_link_scrape", found=pdf_link is not None, link=pdf_link)
                if pdf_link:
                    _stream_to_disk(pdf_link, out_path)
                    _apply_post_processing(out_path, post_process)
                    result = {
                        "path": str(out_path), "filename": out_path.name,
                        "size_bytes": out_path.stat().st_size, "source_url": pdf_link,
                        "method": "static_href_stream",
                    }
                    log_event("download_success", **result)
                    return result

                # Nothing worked.
                log_event("download_failed", url=url, final_url=current_url)
                detail: dict[str, Any] = {
                    "status": "failed",
                    "message": "No PDF found. The page may require a recorded strategy or interactive login.",
                    "requested_url": url,
                    "current_url": current_url,
                }
                if strategy is None:
                    detail["strategy_hint"] = _no_strategy_hint(nav_domain, url)
                raise HTTPException(status_code=404, detail=detail)

            finally:
                try:
                    page.close()
                except PlaywrightError:
                    pass
                _close_context_if_needed(ctx)

    except HTTPException:
        if out_path.exists():
            out_path.unlink()
        raise
    except PlaywrightError as exc:
        if out_path.exists():
            out_path.unlink()
        log_event("download_error", url=url, error=str(exc))
        raise HTTPException(status_code=502, detail=f"Browser automation failed: {exc}") from exc
