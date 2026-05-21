from typing import Any

import requests
from fastapi import HTTPException

from .config import APP_USER_AGENT, REQUEST_TIMEOUT

session = requests.Session()
session.headers.update({"User-Agent": APP_USER_AGENT})


def request_json(url: str, method: str = "GET", **kwargs: Any) -> dict[str, Any]:
    try:
        resp = session.request(method=method, url=url, timeout=REQUEST_TIMEOUT, **kwargs)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Upstream request failed: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Upstream did not return valid JSON.") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Upstream returned unexpected JSON structure.")
    return data
