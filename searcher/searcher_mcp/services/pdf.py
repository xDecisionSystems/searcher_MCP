import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from fastapi import HTTPException

from ..config import DOWNLOAD_DIR, PDF_MAX_MB, REQUEST_TIMEOUT
from ..http_client import session
from ..utils import validate_http_url


def _build_pdf_filename(url: str) -> str:
    parsed = urlparse(url)
    raw_name = Path(parsed.path).name or "downloaded_paper.pdf"
    if not raw_name.lower().endswith(".pdf"):
        raw_name = f"{raw_name}.pdf"
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", raw_name)
    return Path(safe_name[:200]).name


def _unique_output_path(directory: Path, filename: str) -> Path:
    """Return a path that does not exist, appending a short UUID when needed."""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
    return directory / f"{stem}-{uuid.uuid4().hex[:8]}.pdf"


def download_pdf(url: str) -> dict[str, int | str]:
    validate_http_url(url)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = _build_pdf_filename(url)
    out_path = _unique_output_path(DOWNLOAD_DIR, filename)
    max_bytes = PDF_MAX_MB * 1024 * 1024
    size = 0

    try:
        with session.get(url, stream=True, timeout=REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()
            content_type = (resp.headers.get("Content-Type") or "").lower()
            if "pdf" not in content_type and not url.lower().endswith(".pdf"):
                raise HTTPException(
                    status_code=400,
                    detail=f"URL does not appear to be a PDF (Content-Type: {content_type}).",
                )

            with open(out_path, "wb") as file_handle:
                for chunk in resp.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"PDF exceeded configured max size ({PDF_MAX_MB} MB).",
                        )
                    file_handle.write(chunk)
    except HTTPException:
        # Only remove a file we created; a pre-existing file was never opened by us.
        if out_path.exists() and size == 0 or out_path.stat().st_size != size:
            out_path.unlink(missing_ok=True)
        raise
    except requests.RequestException as exc:
        out_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=f"Failed to download PDF: {exc}") from exc

    return {"path": str(out_path), "size_bytes": size, "filename": out_path.name}
