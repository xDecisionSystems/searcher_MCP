#!/usr/bin/env bash
# restart.sh
#
# Restarts all searcher-stack services in dependency order:
#   1. chromium-cdp    (must be up before browser-worker connects)
#   2. browser-worker
#   3. searcher-mcp
#
# Usage:
#   ./deploy/restart.sh            # restart all
#   ./deploy/restart.sh --status   # show service status only

set -euo pipefail

SERVICES=(chromium-cdp browser-worker searcher-mcp)
PORTS=(9222 8010 8000)
HEALTH_URLS=("" "http://127.0.0.1:8010/health" "http://127.0.0.1:8000/health")

STATUS_ONLY=0
[[ "${1:-}" == "--status" ]] && STATUS_ONLY=1

log()  { echo "[restart] $*"; }
pass() { echo "[restart] OK: $*"; }
fail() { echo "[restart] FAIL: $*" >&2; exit 1; }

if [[ "$STATUS_ONLY" == "1" ]]; then
  echo "Service status:"
  for svc in "${SERVICES[@]}"; do
    status="$(systemctl is-active "$svc" 2>/dev/null || echo inactive)"
    echo "  ${svc}: ${status}"
  done
  exit 0
fi

# chromium-cdp must come up before browser-worker tries to connect,
# so restart it first and wait for CDP to respond.
log "Restarting chromium-cdp ..."
systemctl restart chromium-cdp

log "Waiting for Chromium CDP on port ${PORTS[0]} ..."
for i in $(seq 1 15); do
  curl -sf "http://127.0.0.1:${PORTS[0]}/json/version" > /dev/null 2>&1 && break
  [[ "$i" == "15" ]] && fail "chromium-cdp did not come up after 30s"
  sleep 2
done
pass "chromium-cdp"

# Restart remaining services sequentially
for i in 1 2; do
  svc="${SERVICES[$i]}"
  url="${HEALTH_URLS[$i]}"

  log "Restarting ${svc} ..."
  systemctl restart "$svc"

  log "Waiting for ${svc} ..."
  for j in $(seq 1 10); do
    curl -sf "$url" > /dev/null 2>&1 && break
    [[ "$j" == "10" ]] && fail "${svc} did not pass health check after 20s"
    sleep 2
  done
  pass "$svc"
done

echo ""
echo "All services restarted successfully."
echo ""
systemctl is-active "${SERVICES[@]}" 2>/dev/null | paste - - - | \
  awk -v s="${SERVICES[*]}" 'BEGIN{n=split(s,a)} {printf "  %-20s %s\n", a[NR], $0}'
