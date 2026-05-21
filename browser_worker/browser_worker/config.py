import os
import tempfile
from pathlib import Path

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
CDP_URL: str | None = os.getenv("BROWSER_WORKER_CDP_URL")
