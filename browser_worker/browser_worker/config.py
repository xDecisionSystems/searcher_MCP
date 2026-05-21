import os
import tempfile
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent.parent.parent / "VERSION.md"


def load_version_name() -> str:
    default = os.getenv("VERSION_NAME", "browser-worker-dev")
    try:
        content = VERSION_FILE.read_text(encoding="utf-8")
    except OSError:
        return default
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("VERSION_NAME="):
            value = line.split("=", 1)[1].strip()
            return value.strip("'\"") or default
    return default


VERSION_NAME = load_version_name()

APP_USER_AGENT = os.getenv(
    "BROWSER_WORKER_USER_AGENT",
    "browser-worker/1.0 (+https://localhost)",
)
REQUEST_TIMEOUT = float(os.getenv("BROWSER_WORKER_TIMEOUT_SECONDS", "45"))
MAX_DOWNLOAD_MB = int(os.getenv("BROWSER_WORKER_MAX_DOWNLOAD_MB", "100"))
DOWNLOAD_DIR = Path(os.getenv("BROWSER_WORKER_DOWNLOAD_DIR", tempfile.gettempdir()))
HEADLESS = os.getenv("BROWSER_WORKER_HEADLESS", "true").lower() in {"1", "true", "yes", "on"}

_session_dir_raw = os.getenv("BROWSER_WORKER_SESSION_DIR")
SESSION_DIR: Path | None = Path(_session_dir_raw) if _session_dir_raw else None

# URL of a remote Chromium CDP endpoint (e.g. http://127.0.0.1:9222).
# When set, browser_worker connects to that instance instead of launching its own.
# Points to cdp_gateway by default; cdp_gateway proxies to chromium-cdp internally.
CDP_URL: str | None = os.getenv("BROWSER_WORKER_CDP_URL", "http://127.0.0.1:8020")
