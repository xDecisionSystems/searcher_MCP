"""Session recorder for browser_worker.

Records user interactions (navigations, clicks, PDF downloads) while the user
manually performs a download in the noVNC browser. Saves a replayable strategy
JSON file keyed by domain that download.py can use on future requests.

Usage:
    POST /record_session?url=https://mdpi.com/...   — start recording (60s timeout)
    POST /stop_recording                             — stop early and save
"""

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from ..config import CDP_URL, HEADLESS, REQUEST_TIMEOUT, APP_USER_AGENT, SESSION_DIR
from ..logger import log_event

STRATEGIES_DIR = Path(__file__).resolve().parent.parent / "strategies"
STRATEGIES_DIR.mkdir(exist_ok=True)

_DEFAULT_RECORD_SECONDS = 60

# Global recording state (only one session at a time)
_recording_lock = threading.Lock()
_recording_active = False
_stop_event = threading.Event()
_recording_result: dict[str, Any] | None = None
_recording_error: str | None = None


def _strategy_path(domain: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", domain)
    return STRATEGIES_DIR / f"{safe}.json"


def _extract_domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    # Strip port
    return netloc.split(":")[0]


def _url_to_pattern(url: str, base_url: str) -> str:
    """Replace paper-specific IDs in a URL with a wildcard regex pattern.

    Keeps the domain and path structure but replaces long numeric/hex segments
    and common paper identifier patterns so the pattern generalises across papers.
    """
    parsed = urlparse(url)
    # Replace segments that look like IDs: numbers, hex strings, DOI suffixes
    path = re.sub(r"/\d{4,}", "/*", parsed.path)
    path = re.sub(r"/[0-9a-f]{8,}", "/*", path)
    path = re.sub(r"\.[0-9]+\.", ".N.", path)
    base = f"{parsed.scheme}://{parsed.netloc}{path}"
    return base


def _get_browser_context(playwright: Any) -> Any:
    if CDP_URL:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
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
    if CDP_URL:
        return
    try:
        ctx.close()
    except PlaywrightError:
        pass


def _run_recording(url: str, timeout_seconds: int) -> None:
    """Background thread: attach to browser, record events, save strategy."""
    global _recording_active, _recording_result, _recording_error

    steps: list[dict[str, Any]] = []
    domain = _extract_domain(url)
    log_event("recorder_start", url=url, domain=domain, timeout_seconds=timeout_seconds)

    try:
        with sync_playwright() as playwright:
            ctx = _get_browser_context(playwright)

            pages = ctx.pages
            page = pages[0] if pages else ctx.new_page()

            seen_navigations: set[str] = set()
            seen_pdf_urls: set[str] = set()

            # ── Network listener: catch PDF responses ──────────────────────
            def on_response(response: Any) -> None:
                try:
                    resp_url = response.url
                    ct = (response.headers.get("content-type") or "").lower()
                    if "pdf" in ct or resp_url.lower().endswith(".pdf"):
                        if resp_url not in seen_pdf_urls:
                            seen_pdf_urls.add(resp_url)
                            pattern = _url_to_pattern(resp_url, url)
                            steps.append({
                                "type": "wait_for_pdf_response",
                                "url_pattern": pattern,
                                "example_url": resp_url,
                            })
                            log_event("recorder_pdf_response", url=resp_url)
                except Exception:
                    pass

            # ── Navigation listener ────────────────────────────────────────
            def on_framenavigated(frame: Any) -> None:
                try:
                    if frame != page.main_frame:
                        return
                    nav_url = frame.url
                    if nav_url in seen_navigations or nav_url in {"about:blank", ""}:
                        return
                    seen_navigations.add(nav_url)
                    pattern = _url_to_pattern(nav_url, url)
                    steps.append({
                        "type": "navigate",
                        "url_pattern": pattern,
                        "example_url": nav_url,
                    })
                    log_event("recorder_navigate", url=nav_url)
                except Exception:
                    pass

            # ── Click listener injected into page ─────────────────────────
            # We poll for clicks by injecting a JS listener that queues them,
            # then read the queue periodically. This avoids threading issues
            # with Playwright's synchronous API.
            _INJECT_JS = """
            if (!window.__recorder_clicks) {
                window.__recorder_clicks = [];
                document.addEventListener('click', function(e) {
                    var el = e.target;
                    var tag = el.tagName ? el.tagName.toLowerCase() : '';
                    var text = (el.innerText || el.textContent || '').trim().substring(0, 80);
                    var id = el.id ? '#' + el.id : '';
                    var cls = el.className && typeof el.className === 'string'
                        ? '.' + el.className.trim().split(/\\s+/).join('.') : '';
                    var href = el.href || '';
                    window.__recorder_clicks.push({
                        tag: tag,
                        text: text,
                        id: id,
                        cls: cls,
                        href: href
                    });
                }, true);
            }
            """

            _DRAIN_JS = """
            (function() {
                var q = window.__recorder_clicks || [];
                window.__recorder_clicks = [];
                return q;
            })()
            """

            page.on("response", on_response)
            page.on("framenavigated", on_framenavigated)

            # Navigate to starting URL
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=int(REQUEST_TIMEOUT * 1000))
            except PlaywrightError as exc:
                log_event("recorder_navigate_error", url=url, error=str(exc))

            # Inject click listener
            try:
                page.evaluate(_INJECT_JS)
            except PlaywrightError:
                pass

            deadline = time.monotonic() + timeout_seconds
            last_inject = time.monotonic()
            seen_click_texts: set[str] = set()

            while not _stop_event.is_set() and time.monotonic() < deadline:
                time.sleep(0.5)

                # Re-inject after navigations (page context resets)
                if time.monotonic() - last_inject > 2.0:
                    try:
                        page.evaluate(_INJECT_JS)
                        last_inject = time.monotonic()
                    except PlaywrightError:
                        pass

                # Drain click queue
                try:
                    clicks: list[dict[str, Any]] = page.evaluate(_DRAIN_JS) or []
                    for click in clicks:
                        text = click.get("text", "").strip()
                        tag = click.get("tag", "")
                        href = click.get("href", "")
                        el_id = click.get("id", "")
                        cls = click.get("cls", "")

                        # Build the best selector we can
                        if text and tag in ("a", "button"):
                            selector = f"{tag}:has-text('{text}')"
                        elif el_id:
                            selector = el_id
                        elif tag and cls:
                            selector = f"{tag}{cls.split('.')[0] if '.' in cls else cls}"
                        else:
                            selector = tag or "unknown"

                        key = f"{selector}|{href}"
                        if key in seen_click_texts:
                            continue
                        seen_click_texts.add(key)

                        step: dict[str, Any] = {
                            "type": "click",
                            "selector": selector,
                            "element_text": text,
                        }
                        if href:
                            step["href"] = href
                        steps.append(step)
                        log_event("recorder_click", selector=selector, text=text, href=href)
                except PlaywrightError:
                    pass

            page.remove_listener("response", on_response)
            page.remove_listener("framenavigated", on_framenavigated)
            _close_context_if_needed(ctx)

        # ── Deduplicate and clean steps ────────────────────────────────────
        # Remove consecutive duplicate navigations
        cleaned: list[dict[str, Any]] = []
        for step in steps:
            if cleaned and cleaned[-1] == step:
                continue
            cleaned.append(step)

        strategy = {
            "domain": domain,
            "source_url": url,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "timeout_seconds": timeout_seconds,
            "steps": cleaned,
        }

        out_path = _strategy_path(domain)
        out_path.write_text(json.dumps(strategy, indent=2), encoding="utf-8")
        log_event("recorder_saved", domain=domain, steps=len(cleaned), path=str(out_path))

        _recording_result = {
            "status": "saved",
            "domain": domain,
            "steps_recorded": len(cleaned),
            "strategy_file": str(out_path),
            "steps": cleaned,
        }

    except Exception as exc:
        log_event("recorder_error", error=str(exc))
        _recording_error = str(exc)

    finally:
        with _recording_lock:
            _recording_active = False


def start_recording(url: str, timeout_seconds: int = _DEFAULT_RECORD_SECONDS) -> dict[str, Any]:
    global _recording_active, _recording_result, _recording_error

    with _recording_lock:
        if _recording_active:
            return {"status": "already_recording", "message": "A recording session is already active."}
        _recording_active = True
        _recording_result = None
        _recording_error = None
        _stop_event.clear()

    thread = threading.Thread(
        target=_run_recording,
        args=(url, timeout_seconds),
        daemon=True,
        name="recorder",
    )
    thread.start()
    log_event("recorder_thread_started", url=url, timeout_seconds=timeout_seconds)

    return {
        "status": "recording",
        "message": (
            f"Recording started. Perform your download in the browser now. "
            f"Recording will auto-stop after {timeout_seconds}s, "
            f"or call POST /stop_recording to stop early."
        ),
        "domain": _extract_domain(url),
        "timeout_seconds": timeout_seconds,
    }


def stop_recording() -> dict[str, Any]:
    global _recording_active, _recording_result, _recording_error

    with _recording_lock:
        active = _recording_active

    if not active:
        # May have just finished — return result if available
        if _recording_result is not None:
            return _recording_result
        if _recording_error is not None:
            return {"status": "error", "message": _recording_error}
        return {"status": "idle", "message": "No recording session is active."}

    _stop_event.set()

    # Wait up to 5s for the thread to wrap up and write the file
    for _ in range(10):
        time.sleep(0.5)
        with _recording_lock:
            if not _recording_active:
                break

    if _recording_result is not None:
        return _recording_result
    if _recording_error is not None:
        return {"status": "error", "message": _recording_error}
    return {"status": "stopping", "message": "Recording is stopping; call again in a moment."}


def get_recording_status() -> dict[str, Any]:
    with _recording_lock:
        active = _recording_active

    if active:
        return {"status": "recording", "message": "Recording is in progress."}
    if _recording_result is not None:
        return _recording_result
    if _recording_error is not None:
        return {"status": "error", "message": _recording_error}
    return {"status": "idle", "message": "No recording session active."}


def list_strategies() -> list[dict[str, Any]]:
    """Return metadata for all saved strategy files."""
    out: list[dict[str, Any]] = []
    for path in sorted(STRATEGIES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append({
                "domain": data.get("domain", path.stem),
                "recorded_at": data.get("recorded_at"),
                "steps_count": len(data.get("steps", [])),
                "file": path.name,
            })
        except Exception:
            out.append({"file": path.name, "error": "unreadable"})
    return out


def load_strategy(domain: str) -> dict[str, Any] | None:
    """Load a saved strategy for domain, or None if not found."""
    path = _strategy_path(domain)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_strategy(domain: str, strategy: dict[str, Any]) -> None:
    """Write strategy dict to disk for domain, overwriting any existing file."""
    path = _strategy_path(domain)
    path.write_text(json.dumps(strategy, indent=2), encoding="utf-8")
    log_event("strategy_saved_manually", domain=domain, steps=len(strategy.get("steps", [])))


def delete_strategy(domain: str) -> bool:
    """Delete the strategy file for domain. Returns True if deleted."""
    path = _strategy_path(domain)
    if path.exists():
        path.unlink()
        return True
    return False
