#!/usr/bin/env bash
# proxmox_deploy.sh
#
# Creates a single Proxmox LXC and deploys all three services:
#   - searcher-mcp    FastAPI scholar search API          port 8000
#   - browser-worker  FastAPI browser-download API        port 8010
#   - chromium-cdp    Persistent Chromium CDP instance    port 9222 (localhost only)
#
# Requirements (local machine):
#   - SSH access to the Proxmox host as root (or a user with pct privileges)
#
# Usage:
#   ./deploy/proxmox_deploy.sh [options]
#
# Options (all have defaults; set via env var or flag):
#   --proxmox-host   Proxmox SSH target       (default: $PROXMOX_HOST or prompt)
#   --vmid           LXC container ID          (default: $VMID or 200)
#   --storage        Proxmox storage pool      (default: local-lvm)
#   --bridge         LXC network bridge        (default: vmbr0)
#   --repo-url       Git repo URL to clone     (default: $REPO_URL or prompt)
#   --repo-branch    Git branch to deploy      (default: main)
#   --ip             Static IP (CIDR) or dhcp  (default: dhcp)
#   --gateway        Network gateway           (required for static IP)
#   --dns            DNS server                (default: 8.8.8.8)
#   --template       LXC template name         (auto-detected if omitted)
#   --dry-run        Print commands without executing

set -euo pipefail

# ─── Defaults ────────────────────────────────────────────────────────────────
PROXMOX_HOST="${PROXMOX_HOST:-}"
VMID="${VMID:-200}"
STORAGE="${STORAGE:-local-lvm}"
BRIDGE="${BRIDGE:-vmbr0}"
REPO_URL="${REPO_URL:-}"
REPO_BRANCH="${REPO_BRANCH:-main}"
LXC_IP="${LXC_IP:-dhcp}"
GATEWAY="${GATEWAY:-}"
DNS="${DNS:-8.8.8.8}"
TEMPLATE="${TEMPLATE:-}"
DRY_RUN=0

LXC_HOSTNAME="searcher-stack"
SEARCHER_PORT=8000
WORKER_PORT=8010
CDP_PORT=9222
MEMORY=1536
SWAP=512
CORES=2
DISK_SIZE="8G"

# ─── Argument parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --proxmox-host) PROXMOX_HOST="$2"; shift 2 ;;
    --vmid)         VMID="$2";         shift 2 ;;
    --storage)      STORAGE="$2";      shift 2 ;;
    --bridge)       BRIDGE="$2";       shift 2 ;;
    --repo-url)     REPO_URL="$2";     shift 2 ;;
    --repo-branch)  REPO_BRANCH="$2";  shift 2 ;;
    --ip)           LXC_IP="$2";       shift 2 ;;
    --gateway)      GATEWAY="$2";      shift 2 ;;
    --dns)          DNS="$2";          shift 2 ;;
    --template)     TEMPLATE="$2";     shift 2 ;;
    --dry-run)      DRY_RUN=1;         shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ─── Helpers ──────────────────────────────────────────────────────────────────
log()  { echo "[deploy] $*"; }
die()  { echo "[deploy] ERROR: $*" >&2; exit 1; }

ssh_run() {
  local host="$1"; shift
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] ssh root@${host} $*"
    return 0
  fi
  ssh -o StrictHostKeyChecking=accept-new "root@${host}" "$@"
}

lxc_exec() {
  local vmid="$1"; shift
  ssh_run "$PROXMOX_HOST" "pct exec ${vmid} -- bash -c $(printf '%q' "$*")"
}

# ─── Prompt for required values ───────────────────────────────────────────────
if [[ -z "$PROXMOX_HOST" ]]; then
  read -rp "Proxmox host (IP or hostname): " PROXMOX_HOST
fi
[[ -z "$PROXMOX_HOST" ]] && die "PROXMOX_HOST is required."

if [[ -z "$REPO_URL" ]]; then
  read -rp "Git repo URL to clone: " REPO_URL
fi
[[ -z "$REPO_URL" ]] && die "REPO_URL is required."

if [[ "$LXC_IP" != "dhcp" && -z "$GATEWAY" ]]; then
  read -rp "Gateway IP (required for static IP): " GATEWAY
  [[ -z "$GATEWAY" ]] && die "GATEWAY is required when using a static IP."
fi

# ─── Detect or select LXC template ───────────────────────────────────────────
log "Querying available Debian templates on ${PROXMOX_HOST} ..."
TEMPLATES_RAW="$(ssh_run "$PROXMOX_HOST" \
  "pveam list local 2>/dev/null | awk 'NR>1 {print \$1}' | grep -i 'debian' | sort -rV" \
  || true)"

if [[ -z "$TEMPLATE" ]]; then
  if [[ -z "$TEMPLATES_RAW" ]]; then
    die "No Debian templates found. Download one first: pveam download local debian-12-standard_*.tar.zst"
  fi
  mapfile -t TEMPLATE_LIST <<< "$TEMPLATES_RAW"
  log "Available Debian templates:"
  for i in "${!TEMPLATE_LIST[@]}"; do
    echo "  [$i] ${TEMPLATE_LIST[$i]}"
  done
  read -rp "Select template index or press Enter for newest (${TEMPLATE_LIST[0]}): " TMPL_CHOICE
  if [[ -z "$TMPL_CHOICE" || "$TMPL_CHOICE" == "auto" ]]; then
    TEMPLATE="${TEMPLATE_LIST[0]}"
  else
    TEMPLATE="${TEMPLATE_LIST[$TMPL_CHOICE]}"
  fi
fi
log "Using template: ${TEMPLATE}"

# ─── Confirm before proceeding ───────────────────────────────────────────────
echo ""
echo "  Proxmox host : ${PROXMOX_HOST}"
echo "  VMID         : ${VMID}"
echo "  Hostname     : ${LXC_HOSTNAME}"
echo "  IP           : ${LXC_IP}"
echo "  Template     : ${TEMPLATE}"
echo "  Memory       : ${MEMORY} MB    Disk: ${DISK_SIZE}    Cores: ${CORES}"
echo "  Repo         : ${REPO_URL} (branch: ${REPO_BRANCH})"
echo ""
echo "  Services to install:"
echo "    searcher-mcp    port ${SEARCHER_PORT}"
echo "    browser-worker  port ${WORKER_PORT}"
echo "    chromium-cdp    port ${CDP_PORT} (localhost only)"
echo ""
if [[ "$DRY_RUN" == "1" ]]; then
  echo "  *** DRY RUN — no changes will be made ***"
  echo ""
fi
read -rp "Proceed? [y/N] " CONFIRM
[[ "${CONFIRM,,}" == "y" ]] || { log "Aborted."; exit 0; }

# ─── Create LXC ───────────────────────────────────────────────────────────────
log "Checking if VMID ${VMID} exists ..."
EXISTS="$(ssh_run "$PROXMOX_HOST" "pct list | awk 'NR>1 {print \$1}' | grep -w '${VMID}' || true")"
if [[ -n "$EXISTS" ]]; then
  log "VMID ${VMID} exists — stopping and destroying ..."
  ssh_run "$PROXMOX_HOST" "pct stop ${VMID} --skiplock 1 2>/dev/null || true"
  ssh_run "$PROXMOX_HOST" "pct destroy ${VMID} --purge 1"
fi

NET_CONFIG="name=eth0,bridge=${BRIDGE},ip=dhcp"
if [[ "$LXC_IP" != "dhcp" ]]; then
  NET_CONFIG="name=eth0,bridge=${BRIDGE},ip=${LXC_IP},gw=${GATEWAY}"
fi

log "Creating LXC ${VMID} (${LXC_HOSTNAME}) ..."
ssh_run "$PROXMOX_HOST" \
  "pct create ${VMID} ${TEMPLATE} \
    --hostname ${LXC_HOSTNAME} \
    --storage ${STORAGE} \
    --rootfs ${STORAGE}:${DISK_SIZE} \
    --memory ${MEMORY} \
    --swap ${SWAP} \
    --cores ${CORES} \
    --net0 ${NET_CONFIG} \
    --nameserver ${DNS} \
    --unprivileged 1 \
    --features nesting=1 \
    --start 1 \
    --onboot 1"

log "Waiting for LXC to be ready ..."
ssh_run "$PROXMOX_HOST" "sleep 6"

# ─── System packages ──────────────────────────────────────────────────────────
log "Installing system packages ..."
lxc_exec "$VMID" "apt-get update -qq && apt-get install -y -qq python3 python3-venv git curl chromium"

# ─── Clone repo ───────────────────────────────────────────────────────────────
log "Cloning ${REPO_URL} (branch: ${REPO_BRANCH}) ..."
lxc_exec "$VMID" "git clone --branch ${REPO_BRANCH} --depth 1 ${REPO_URL} /opt/repo"

# ─── Install searcher ─────────────────────────────────────────────────────────
log "Installing searcher ..."
lxc_exec "$VMID" "
  ln -s /opt/repo/searcher /opt/searcher
  cd /opt/searcher
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
  cp .env.example .env
  cp deploy/searcher-mcp.service /etc/systemd/system/searcher-mcp.service
  systemctl daemon-reload
  systemctl enable searcher-mcp
  systemctl start searcher-mcp
"
log "Waiting for searcher-mcp ..."
lxc_exec "$VMID" "sleep 4"
lxc_exec "$VMID" "curl -sf http://127.0.0.1:${SEARCHER_PORT}/health || { echo 'searcher-mcp health check failed'; exit 1; }"
log "searcher-mcp PASSED."

# ─── Install browser_worker ───────────────────────────────────────────────────
log "Installing browser_worker ..."
lxc_exec "$VMID" "
  ln -s /opt/repo/browser_worker /opt/browser_worker
  cd /opt/browser_worker
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
"

log "Installing Playwright Chromium ..."
lxc_exec "$VMID" "
  cd /opt/browser_worker
  .venv/bin/python -m playwright install-deps chromium 2>&1 | tail -5
  .venv/bin/python -m playwright install chromium 2>&1 | tail -5
"

# ─── Install chromium-cdp ─────────────────────────────────────────────────────
log "Installing chromium-cdp service ..."
lxc_exec "$VMID" "
  mkdir -p /opt/browser_worker/chromium-profile
  cp /opt/browser_worker/deploy/chromium-cdp.service /etc/systemd/system/chromium-cdp.service
  systemctl daemon-reload
  systemctl enable chromium-cdp
  systemctl start chromium-cdp
"
log "Waiting for Chromium CDP on port ${CDP_PORT} ..."
lxc_exec "$VMID" "
  for i in \$(seq 1 12); do
    curl -sf http://127.0.0.1:${CDP_PORT}/json/version > /dev/null && exit 0
    sleep 2
  done
  echo 'chromium-cdp did not start in time'; exit 1
"
log "chromium-cdp PASSED."

# ─── Wire CDP URL into browser_worker env and start it ───────────────────────
log "Configuring and starting browser-worker ..."
lxc_exec "$VMID" "
  cp /opt/browser_worker/.env.example /opt/browser_worker/.env
  sed -i 's|^BROWSER_WORKER_CDP_URL=.*|BROWSER_WORKER_CDP_URL=http://127.0.0.1:${CDP_PORT}|' /opt/browser_worker/.env
  grep -q 'BROWSER_WORKER_CDP_URL' /opt/browser_worker/.env || \
    echo 'BROWSER_WORKER_CDP_URL=http://127.0.0.1:${CDP_PORT}' >> /opt/browser_worker/.env
  cp /opt/browser_worker/deploy/browser-worker.service /etc/systemd/system/browser-worker.service
  systemctl daemon-reload
  systemctl enable browser-worker
  systemctl start browser-worker
"
log "Waiting for browser-worker ..."
lxc_exec "$VMID" "sleep 4"
lxc_exec "$VMID" "curl -sf http://127.0.0.1:${WORKER_PORT}/health || { echo 'browser-worker health check failed'; exit 1; }"
log "browser-worker PASSED."

# ─── Summary ──────────────────────────────────────────────────────────────────
log ""
log "=== Deployment complete ==="
log ""

LXC_ACTUAL_IP="$(ssh_run "$PROXMOX_HOST" \
  "pct exec ${VMID} -- hostname -I 2>/dev/null | awk '{print \$1}'" || echo "(check manually)")"

echo "  searcher-mcp    http://${LXC_ACTUAL_IP}:${SEARCHER_PORT}/health"
echo "  searcher docs   http://${LXC_ACTUAL_IP}:${SEARCHER_PORT}/docs"
echo "  browser-worker  http://${LXC_ACTUAL_IP}:${WORKER_PORT}/health"
echo "  chromium-cdp    port ${CDP_PORT} (localhost inside LXC only)"
echo ""
echo "  Next steps:"
echo "    1. Add API keys to /opt/searcher/.env on VMID ${VMID},"
echo "       then: systemctl restart searcher-mcp"
echo ""
echo "    2. To log into publisher portals (ScienceDirect, IEEE, etc.):"
echo "       a. SSH port-forward the CDP port:"
echo "            ssh -L 9222:127.0.0.1:${CDP_PORT} root@${LXC_ACTUAL_IP}"
echo "       b. In Chrome/Edge go to: chrome://inspect"
echo "          Click 'Configure', add: localhost:9222"
echo "          Click 'inspect' on the remote target and log in."
echo "       c. Session saves to /opt/browser_worker/chromium-profile — persists across restarts."
