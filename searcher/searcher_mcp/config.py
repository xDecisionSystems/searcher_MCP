import os
import tempfile
from pathlib import Path

APP_USER_AGENT = os.getenv(
    "MCP_USER_AGENT",
    "searcher-mcp/1.0 (+https://localhost)",
)
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
PDF_MAX_MB = int(os.getenv("PDF_MAX_MB", "50"))
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", tempfile.gettempdir()))
VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION.md"

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
IEEE_XPLORE_API_KEY = os.getenv("IEEE_XPLORE_API_KEY")
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
WEB_OF_SCIENCE_API_KEY = os.getenv("WEB_OF_SCIENCE_API_KEY")
ELSEVIER_API_KEY = os.getenv("ELSEVIER_API_KEY")


def load_version_name() -> str:
    default_version_name = os.getenv("VERSION_NAME", "searcher-mcp-dev")
    try:
        content = VERSION_FILE.read_text(encoding="utf-8")
    except OSError:
        return default_version_name

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("VERSION_NAME="):
            value = line.split("=", 1)[1].strip()
            return value.strip("'\"") or default_version_name
    return default_version_name


VERSION_NAME = load_version_name()
