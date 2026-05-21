# cdp_gateway

JWT-authenticated login page and WebSocket proxy for Chromium CDP access. Part of the `searcher-stack` deployment.

## Purpose

- Provides a login page where users enter a secret key and select a session duration
- Issues a signed JWT on successful login
- Proxies all Chrome DevTools Protocol (CDP) HTTP and WebSocket traffic to the local `chromium-cdp` instance
- Embeds the JWT into WebSocket URLs returned by `/json` so `chrome://inspect` passes it automatically
- Expired or missing tokens are rejected — no unauthenticated CDP access

## Endpoints

- `GET /login` — login page
- `POST /login` — submit key + duration, receive JWT
- `GET /json` — CDP target list (JWT required, URLs rewritten with token)
- `GET /json/version` — CDP version info (JWT required)
- `GET /json/*` — other CDP HTTP endpoints (JWT required)
- `WS /devtools/{path}?token=<jwt>` — CDP WebSocket proxy (JWT required)

## Deployment

Deployed as part of the full stack via `deploy/proxmox_deploy.sh` at the repo root.

- Working directory inside LXC: `/opt/repo/cdp_gateway`
- Env file: `/opt/repo/.env` (shared with all services)
- Service: `cdp-gateway.service`
- Port: `8020`
- Depends on: `chromium-cdp.service`

## First Run — Set Password

On first visit, the login page shows a **Set password** form instead of the login form. Enter and confirm your password (minimum 8 characters). The password is hashed with bcrypt and stored at `password.hash` — it is never stored in plaintext and is not recoverable even by root.

## Logging In

1. Open `http://<lxc-ip>:8020/login`
2. Enter your password and select a session duration (30min / 60min / 24hr)
3. Click **Generate token** — the page shows the JWT and `chrome://inspect` instructions
4. In Chrome/Edge: `chrome://inspect` → **Configure** → add `<lxc-ip>:8020` → **Done**
5. Click **inspect** on the remote target to open DevTools

The token is embedded in the WebSocket URL returned by `/json` — no manual token entry needed in Chrome.

## Local Testing

```bash
cd cdp_gateway
set -a && source ../.env.dev && set +a
../.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8020
```

Requires `chromium-cdp` to be running on port 9222 locally.

## Environment Variables

All keys are shared via the root `.env.example`.

- `CDP_JWT_SECRET` — secret used to sign JWTs (required; password is set via the login page, not env)
- `CDP_GATEWAY_PORT` — port to listen on (default `8020`)
- `BROWSER_WORKER_CDP_URL` — upstream CDP URL to proxy to (default `http://127.0.0.1:9222`)

Generate JWT secret:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"  # CDP_JWT_SECRET
```
