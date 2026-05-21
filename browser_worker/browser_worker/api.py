from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .services.download import download_paper_via_browser

app = FastAPI(title="Searcher Browser Worker", version="1.0.0")


class DownloadRequest(BaseModel):
    url: str = Field(..., description="Target page URL that should eventually lead to a PDF.")
    filename: str | None = Field(default=None, description="Optional output filename.")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "browser_worker"}


@app.post("/download_paper")
def download_paper(request: DownloadRequest) -> dict[str, Any]:
    return download_paper_via_browser(url=request.url, filename=request.filename)
