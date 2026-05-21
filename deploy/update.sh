#!/usr/bin/env bash
# update.sh
#
# Updates all searcher-stack services on the LXC by pulling the latest code
# from GitHub, reinstalling dependencies, and restarting services in order.
#
# Must be run as root inside the LXC (or via: pct exec <vmid> -- bash /opt/repo/deploy/update.sh)
#
# Usage:
#   ./deploy/update.sh [--branch <branch>] [--dry-run]

set -euo pipefail

REPO_DIR="/opt/repo"
REPO_URL="https://github.com/xDecisionSystems/searcher_MCP"
BRANCH="${BRANCH:-main}"
DRY_RUN=0

SEARCHER_DIR="/opt/repo/searcher"
WORKER_DIR="/opt/repo/browser_worker"
GATEWAY_DIR="/opt/repo/cdp_gateway"
CDP_PORT=9222
SEARCHER_PORT=8000
WORKER_PORT=8010
GATEWAY_PORT=8020

# ─── Argument parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch)   BRANCH="$2"; shift 2 ;;
    --dry-run)  DRY_RUN=1;   shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ─── Helpers ──────────────────────────────────────────────────────────────────
log()  { echo "[update] $*"; }
die()  { echo "[update] ERROR: $*" >&2; exit 1; }
pass() { echo "[update] OK: $*"; }

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

[[ "${EUID}" -ne 0 ]] && die "Run as root."
[[ -d "$REPO_DIR" ]] || die "${REPO_DIR} not found. Has the LXC been deployed?"

# ─── Show current versions ────────────────────────────────────────────────────
read_version() {
  local f="${REPO_DIR}/VERSION.md"
  [[ -f "$f" ]] && grep -E '^VERSION_NAME=' "$f" | cut -d= -f2- | tr -d '"'"'" || echo "unknown"
}

OLD_VERSION="$(read_version)"
log "Current version: ${OLD_VERSION}"

# ─── Pull latest code ─────────────────────────────────────────────────────────
log "Pulling latest code from ${REPO_URL} (branch: ${BRANCH}) ..."
run git -C "$REPO_DIR" fetch --depth 1 origin "${BRANCH}"
run git -C "$REPO_DIR" reset --hard "origin/${BRANCH}"

NEW_VERSION="$(read_version)"
log "New version: ${NEW_VERSION}"

# ─── Confirm ──────────────────────────────────────────────────────────────────
if [[ "$DRY_RUN" == "0" ]]; then
  echo ""
  read -rp "[update] Proceed with update and restart? [Y/n] " CONFIRM
  CONFIRM="${CONFIRM:-Y}"
  [[ "${CONFIRM,,}" == "n" ]] && { log "Aborted."; exit 0; }
fi

# ─── Update searcher deps ─────────────────────────────────────────────────────
log "Updating searcher dependencies ..."
run "${SEARCHER_DIR}/.venv/bin/python" -m pip install --quiet --upgrade pip
run "${SEARCHER_DIR}/.venv/bin/python" -m pip install --quiet -r "${SEARCHER_DIR}/requirements.txt"

log "Refreshing searcher-mcp systemd unit ..."
run cp "${SEARCHER_DIR}/deploy/searcher-mcp.service" /etc/systemd/system/searcher-mcp.service

# ─── Update browser_worker deps ───────────────────────────────────────────────
log "Updating browser_worker dependencies ..."
run "${WORKER_DIR}/.venv/bin/python" -m pip install --quiet --upgrade pip
run "${WORKER_DIR}/.venv/bin/python" -m pip install --quiet -r "${WORKER_DIR}/requirements.txt"
run "${WORKER_DIR}/.venv/bin/python" -m playwright install chromium

log "Refreshing browser-worker and chromium-cdp systemd units ..."
run cp "${WORKER_DIR}/deploy/browser-worker.service"  /etc/systemd/system/browser-worker.service
run cp "${WORKER_DIR}/deploy/chromium-cdp.service"    /etc/systemd/system/chromium-cdp.service

# ─── Update cdp_gateway deps ──────────────────────────────────────────────────
log "Updating cdp_gateway dependencies ..."
run "${GATEWAY_DIR}/.venv/bin/python" -m pip install --quiet --upgrade pip
run "${GATEWAY_DIR}/.venv/bin/python" -m pip install --quiet -r "${GATEWAY_DIR}/requirements.txt"

log "Refreshing cdp-gateway systemd unit ..."
run cp "${GATEWAY_DIR}/deploy/cdp-gateway.service" /etc/systemd/system/cdp-gateway.service

# ─── Reload systemd ───────────────────────────────────────────────────────────
run systemctl daemon-reload

# ─── Restart services in dependency order ────────────────────────────────────
log "Restarting chromium-cdp ..."
run systemctl restart chromium-cdp

log "Waiting for Chromium CDP on port ${CDP_PORT} ..."
for i in $(seq 1 15); do
  curl -sf "http://127.0.0.1:${CDP_PORT}/json/version" > /dev/null 2>&1 && break
  [[ "$i" == "15" ]] && die "chromium-cdp did not come up after 30s"
  sleep 2
done
pass "chromium-cdp"

log "Restarting browser-worker ..."
run systemctl restart browser-worker
for i in $(seq 1 10); do
  curl -sf "http://127.0.0.1:${WORKER_PORT}/health" > /dev/null 2>&1 && break
  [[ "$i" == "10" ]] && die "browser-worker did not pass health check"
  sleep 2
done
pass "browser-worker"

log "Restarting searcher-mcp ..."
run systemctl restart searcher-mcp
for i in $(seq 1 10); do
  curl -sf "http://127.0.0.1:${SEARCHER_PORT}/health" > /dev/null 2>&1 && break
  [[ "$i" == "10" ]] && die "searcher-mcp did not pass health check"
  sleep 2
done
pass "searcher-mcp"

log "Restarting cdp-gateway ..."
run systemctl restart cdp-gateway
for i in $(seq 1 10); do
  curl -sf "http://127.0.0.1:${GATEWAY_PORT}/login" > /dev/null 2>&1 && break
  [[ "$i" == "10" ]] && die "cdp-gateway did not pass health check"
  sleep 2
done
pass "cdp-gateway"

# ─── Summary ──────────────────────────────────────────────────────────────────
echo ""
log "=== Update complete ==="
log "  ${OLD_VERSION} → ${NEW_VERSION}"
echo ""
systemctl is-active chromium-cdp browser-worker searcher-mcp cdp-gateway 2>/dev/null | \
  paste - - - - | awk '{printf "  %-20s %-20s %-20s %-20s\n", "chromium-cdp:"$1, "browser-worker:"$2, "searcher-mcp:"$3, "cdp-gateway:"$4}'
