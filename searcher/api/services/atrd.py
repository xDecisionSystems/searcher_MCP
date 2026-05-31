import re
import uuid
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException

from ..config import DOWNLOAD_DIR, PDF_MAX_MB, REQUEST_TIMEOUT

_ATRD_URL = "https://www.atrdsymposium.org/past-seminars/1st-symposium/papers-and-presentations/"
_DRIVE_FILE_RE = re.compile(r"/file/d/([^/]+)/")
_DRIVE_EXPORT_TMPL = "https://drive.google.com/uc?export=download&id={}"
_SAFE_CHAR_RE = re.compile(r"[^a-z0-9]+")
_AUTHOR_SPLIT_RE = re.compile(r",\s*|\s+and\s+")


def _clean_filename(title: str) -> str:
    slug = _SAFE_CHAR_RE.sub("_", title.lower()).strip("_")
    return (slug[:180] or "paper") + ".pdf"


def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
    return directory / f"{stem}_{uuid.uuid4().hex[:8]}.pdf"


def _drive_download_url(href: str) -> str | None:
    m = _DRIVE_FILE_RE.search(href)
    if not m:
        return None
    return _DRIVE_EXPORT_TMPL.format(m.group(1))


def _fetch_html(url: str) -> str:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; searcher/1.0)"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch ATRD page: {exc}") from exc


def _parse_papers(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    papers: list[dict[str, Any]] = []

    for article in soup.find_all("article"):
        badge = article.find("span", class_="badge")
        section = badge.get_text(" ", strip=True) if badge else ""

        for li in article.find_all("li", class_="mb-5"):
            h3 = li.find("h3")
            if not h3:
                continue

            is_best_paper = bool(h3.find("i", class_=lambda c: c and "bx-trophy" in c))
            title = h3.get_text(" ", strip=True)

            em = li.find("em")
            authors_raw = em.get_text(" ", strip=True) if em else ""
            authors = [a.strip() for a in _AUTHOR_SPLIT_RE.split(authors_raw) if a.strip()]

            full_paper_url = ""
            presentation_url = ""
            for a in li.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(" ", strip=True)
                if "Full Paper" in text:
                    full_paper_url = href
                elif "Presentation" in text:
                    presentation_url = href

            papers.append({
                "title": title,
                "authors": authors,
                "section": section,
                "is_best_paper": is_best_paper,
                "full_paper_url": full_paper_url,
                "presentation_url": presentation_url,
            })

    return papers


def _download_file(download_url: str, out_path: Path) -> int:
    max_bytes = PDF_MAX_MB * 1024 * 1024
    size = 0
    try:
        with requests.get(download_url, stream=True, timeout=60, allow_redirects=True) as resp:
            resp.raise_for_status()
            with open(out_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        out_path.unlink(missing_ok=True)
                        raise HTTPException(
                            status_code=413,
                            detail=f"File exceeded max size ({PDF_MAX_MB} MB): {out_path.name}",
                        )
                    fh.write(chunk)
    except HTTPException:
        raise
    except requests.RequestException as exc:
        out_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=f"Download failed for {out_path.name}: {exc}") from exc
    return size


def search_atrd_papers(url: str) -> dict[str, Any]:
    """Return all paper metadata from an ATRD symposium papers page without downloading files."""
    html = _fetch_html(url)
    papers = _parse_papers(html)
    return {
        "source": url,
        "count": len(papers),
        "papers": papers,
    }


def download_atrd_paper(paper: dict[str, Any]) -> dict[str, Any]:
    """Download the full-paper PDF for a single ATRD paper record from /search_atrd_papers."""
    title = paper.get("title", "").strip()
    href = paper.get("full_paper_url", "").strip()

    if not href:
        raise HTTPException(status_code=400, detail="Paper record has no full_paper_url.")

    download_url = _drive_download_url(href)
    if not download_url:
        raise HTTPException(status_code=400, detail=f"full_paper_url is not a Google Drive file link: {href}")

    save_dir = DOWNLOAD_DIR / "atrd"
    save_dir.mkdir(parents=True, exist_ok=True)

    filename = _clean_filename(title or href)
    existing = save_dir / filename
    if existing.exists():
        return {**paper, "local_path": str(existing), "size_bytes": existing.stat().st_size}

    out_path = _unique_path(save_dir, filename)
    size = _download_file(download_url, out_path)
    return {**paper, "local_path": str(out_path), "size_bytes": size}
