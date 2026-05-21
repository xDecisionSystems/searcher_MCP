import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import websockets
from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .config import CDP_URL, DURATIONS, GATEWAY_PORT, JWT_SECRET
from .session import (
    issue_token,
    password_is_set,
    set_password,
    validate_token,
    verify_password,
)

app = FastAPI(title="CDP Gateway", docs_url=None, redoc_url=None)

_templates = Jinja2Templates(
    directory=str(Path(__file__).parent / "templates")
)


def _render(request: Request, context: dict, status_code: int = 200) -> HTMLResponse:
    """Compatibility wrapper — works with both old and new Starlette TemplateResponse."""
    context.setdefault("request", request)
    return _templates.TemplateResponse(
        request=request,
        name="login.html",
        context=context,
        status_code=status_code,
    )


def _ctx(request: Request, **kwargs: Any) -> dict:
    """Build a full template context with safe defaults."""
    return {
        "request": request,
        "needs_setup": not password_is_set(),
        "token": None,
        "error": None,
        "durations": list(DURATIONS.keys()),
        "gateway_host": None,
        "open_result": None,
        **kwargs,
    }


def _cdp_ws_base() -> str:
    parsed = urlparse(CDP_URL)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9222
    return f"ws://{host}:{port}"


def _cdp_http_base() -> str:
    parsed = urlparse(CDP_URL)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9222
    return f"http://{host}:{port}"


def _extract_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    cookie = request.cookies.get("cdp_token", "")
    if cookie:
        return cookie
    return request.query_params.get("token", "")


def _extract_token_ws(websocket: WebSocket) -> str:
    token = websocket.query_params.get("token", "")
    if token:
        return token
    return websocket.cookies.get("cdp_token", "")


def _rewrite_json_entry(entry: Any, token: str, gateway_host: str) -> Any:
    if not isinstance(entry, dict):
        return entry
    ws_url = entry.get("webSocketDebuggerUrl", "")
    if ws_url:
        parsed = urlparse(ws_url)
        entry["webSocketDebuggerUrl"] = (
            f"ws://{gateway_host}/devtools{parsed.path}?token={token}"
        )
    entry.pop("devtoolsFrontendUrl", None)
    return entry


# ─── Root redirect ────────────────────────────────────────────────────────────

@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/login")


# ─── Login page ───────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return _render(request, _ctx(request))


# ─── Set-password (first run) ─────────────────────────────────────────────────

@app.post("/set-password", response_class=HTMLResponse)
async def set_password_submit(
    request: Request,
    password: str = Form(...),
    confirm: str = Form(...),
) -> Any:
    if password_is_set():
        return _render(request, _ctx(request,
            needs_setup=False,
            error="Password is already set. Log in below.",
        ))
    if len(password) < 8:
        return _render(request, _ctx(request,
            needs_setup=True,
            error="Password must be at least 8 characters.",
        ), status_code=400)
    if password != confirm:
        return _render(request, _ctx(request,
            needs_setup=True,
            error="Passwords do not match.",
        ), status_code=400)

    set_password(password)
    return _render(request, _ctx(request, needs_setup=False))


# ─── Login ────────────────────────────────────────────────────────────────────

@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    password: str = Form(...),
    duration: str = Form(...),
) -> Any:
    if not password_is_set():
        return RedirectResponse(url="/login", status_code=303)

    if not JWT_SECRET:
        return _render(request, _ctx(request,
            needs_setup=False,
            error="CDP_JWT_SECRET is not configured on the server.",
        ), status_code=500)

    if duration not in DURATIONS:
        return _render(request, _ctx(request,
            needs_setup=False,
            error="Invalid duration.",
        ), status_code=400)

    if not verify_password(password):
        return _render(request, _ctx(request,
            needs_setup=False,
            error="Incorrect password.",
        ), status_code=401)

    token = issue_token(duration)
    gateway_host = request.headers.get("host", f"localhost:{GATEWAY_PORT}")

    response = _render(request, _ctx(request,
        needs_setup=False,
        token=token,
        gateway_host=gateway_host,
    ))
    response.set_cookie(
        key="cdp_token",
        value=token,
        httponly=True,
        max_age=DURATIONS[duration],
        samesite="lax",
    )
    return response


# ─── CDP HTTP passthrough ─────────────────────────────────────────────────────

@app.post("/open", response_class=HTMLResponse)
async def open_url(
    request: Request,
    url: str = Form(...),
    token: str = Form(...),
) -> Any:
    if not validate_token(token):
        return _render(request, _ctx(request,
            needs_setup=False,
            error="Invalid or expired token. Please generate a new one.",
            token=token,
            gateway_host=request.headers.get("host", f"localhost:{GATEWAY_PORT}"),
        ), status_code=401)
    async with httpx.AsyncClient() as client:
        resp = await client.put(f"{_cdp_http_base()}/json/new?{url}")
    gateway_host = request.headers.get("host", f"localhost:{GATEWAY_PORT}")
    data = resp.json()
    if isinstance(data, dict):
        data = _rewrite_json_entry(data, token, gateway_host)
    return _render(request, _ctx(request,
        needs_setup=False,
        token=token,
        gateway_host=gateway_host,
        open_result=f"Opened: {url}",
    ))


@app.api_route("/json/new", methods=["GET", "PUT", "POST"])
async def cdp_json_new(request: Request) -> Any:
    token = _extract_token(request)
    if not validate_token(token):
        return JSONResponse({"error": "Access denied. Authenticate at /login."}, status_code=403)
    url = request.query_params.get("url", "about:blank")
    async with httpx.AsyncClient() as client:
        resp = await client.put(f"{_cdp_http_base()}/json/new?{url}")
    data = resp.json()
    gateway_host = request.headers.get("host", f"localhost:{GATEWAY_PORT}")
    if isinstance(data, dict):
        data = _rewrite_json_entry(data, token, gateway_host)
    return JSONResponse(data, status_code=resp.status_code)


@app.api_route("/json/activate/{target_id}", methods=["GET", "POST"])
async def cdp_json_activate(request: Request, target_id: str) -> Any:
    token = _extract_token(request)
    if not validate_token(token):
        return JSONResponse({"error": "Access denied. Authenticate at /login."}, status_code=403)
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{_cdp_http_base()}/json/activate/{target_id}")
    return JSONResponse(resp.json() if resp.content else {}, status_code=resp.status_code)


@app.api_route("/json/close/{target_id}", methods=["GET", "POST"])
async def cdp_json_close(request: Request, target_id: str) -> Any:
    token = _extract_token(request)
    if not validate_token(token):
        return JSONResponse({"error": "Access denied. Authenticate at /login."}, status_code=403)
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{_cdp_http_base()}/json/close/{target_id}")
    return JSONResponse(resp.json() if resp.content else {}, status_code=resp.status_code)


@app.api_route("/json/version", methods=["GET"])
async def cdp_json_version(request: Request) -> Any:
    token = _extract_token(request)
    if not validate_token(token):
        return JSONResponse({"error": "Access denied. Authenticate at /login."}, status_code=403)
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{_cdp_http_base()}/json/version")
    data = resp.json()
    gateway_host = request.headers.get("host", f"localhost:{GATEWAY_PORT}")
    if isinstance(data, dict):
        data = _rewrite_json_entry(data, token, gateway_host)
    return JSONResponse(data, status_code=resp.status_code)


@app.api_route("/json", methods=["GET"])
@app.api_route("/json/list", methods=["GET"])
async def cdp_json_list(request: Request) -> Any:
    token = _extract_token(request)
    if not validate_token(token):
        return JSONResponse({"error": "Access denied. Authenticate at /login."}, status_code=403)
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{_cdp_http_base()}/json")
    gateway_host = request.headers.get("host", f"localhost:{GATEWAY_PORT}")
    data = resp.json()
    if isinstance(data, list):
        data = [_rewrite_json_entry(e, token, gateway_host) for e in data]
    return JSONResponse(data, status_code=resp.status_code)


@app.api_route("/json/{path:path}", methods=["GET"])
async def cdp_json_other(request: Request, path: str) -> Any:
    token = _extract_token(request)
    if not validate_token(token):
        return JSONResponse({"error": "Access denied. Authenticate at /login."}, status_code=403)
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{_cdp_http_base()}/json/{path}")
    return JSONResponse(resp.json(), status_code=resp.status_code)


# ─── CDP WebSocket proxy ──────────────────────────────────────────────────────

@app.websocket("/devtools/{path:path}")
async def cdp_ws_proxy(websocket: WebSocket, path: str) -> None:
    token = _extract_token_ws(websocket)
    if not validate_token(token):
        await websocket.close(code=4403)
        return

    await websocket.accept()
    upstream_url = f"{_cdp_ws_base()}/devtools/{path}"

    try:
        async with websockets.connect(upstream_url) as upstream:

            async def client_to_upstream() -> None:
                try:
                    while True:
                        msg = await websocket.receive_text()
                        await upstream.send(msg)
                except (WebSocketDisconnect, Exception):
                    pass

            async def upstream_to_client() -> None:
                try:
                    async for msg in upstream:
                        if isinstance(msg, bytes):
                            await websocket.send_bytes(msg)
                        else:
                            await websocket.send_text(msg)
                except Exception:
                    pass

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except Exception:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
