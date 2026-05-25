#!/usr/bin/env bash
# proxmox_deploy.sh
#
# Creates a single Proxmox LXC and deploys all services:
#   - searcher-mcp      FastAPI scholar search API        port 8000
#   - browser-worker    FastAPI browser-download API      port 8010
#   - xvfb              Virtual display (Xvfb :99)
#   - x11vnc            VNC server on the virtual display port 5900
#   - chromium-display  Chromium browser with GUI + CDP   port 9222 (localhost)
#   - novnc             Browser-based VNC client          port 6080
#
# Requirements (local machine):
#   - SSH access to the Proxmox host as root (or a user with pct privileges)
#
# Usage:
#   ./deploy/proxmox_deploy.sh [options]
#
# Options (all have defaults; set via env var or flag):
#   --proxmox-host       Proxmox SSH target              (default: $PROXMOX_HOST or prompt)
#   --hostname-postfix   Suffix appended to hostname      (default: prompt, e.g. "aev" → searcher-stack-aev)
#   --vmid           LXC container ID          (default: $VMID or 200)
#   --storage        Proxmox storage pool      (default: local-lvm)
#   --bridge         LXC network bridge        (default: vmbr0)
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
REPO_URL="https://github.com/xDecisionSystems/searcher_MCP"
REPO_BRANCH="${REPO_BRANCH:-main}"
LXC_IP="${LXC_IP:-dhcp}"
GATEWAY="${GATEWAY:-}"
DNS="${DNS:-8.8.8.8}"
TEMPLATE="${TEMPLATE:-}"
DRY_RUN=0

LXC_HOSTNAME_BASE="searcher-stack"
LXC_HOSTNAME_POSTFIX="${LXC_HOSTNAME_POSTFIX:-}"
LXC_HOSTNAME=""  # resolved after prompts
SEARCHER_PORT=8000
WORKER_PORT=8010
CDP_PORT=9222
NOVNC_PORT=6080
MEMORY=1536
SWAP=512
CORES=2
DISK_SIZE="8G"

# ─── Argument parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --proxmox-host)      PROXMOX_HOST="$2";        shift 2 ;;
    --hostname-postfix)  LXC_HOSTNAME_POSTFIX="$2"; shift 2 ;;
    --vmid)         VMID="$2";         shift 2 ;;
    --storage)      STORAGE="$2";      shift 2 ;;
    --bridge)       BRIDGE="$2";       shift 2 ;;
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

SSH_SOCKET=""

# Open a single multiplexed SSH connection; all subsequent ssh_run calls reuse it.
ssh_open() {
  local host="$1"
  SSH_SOCKET="$(mktemp -u /tmp/ssh-mux-XXXXXX)"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] ssh -M -o ControlMaster=yes ... root@${host}"
    return 0
  fi
  ssh -o StrictHostKeyChecking=accept-new \
      -o ControlMaster=yes \
      -o ControlPath="${SSH_SOCKET}" \
      -o ControlPersist=yes \
      -fN "root@${host}"
  trap 'ssh_close' EXIT
}

ssh_close() {
  if [[ -n "$SSH_SOCKET" && "$DRY_RUN" != "1" ]]; then
    ssh -o ControlPath="${SSH_SOCKET}" -O exit "root@${PROXMOX_HOST}" 2>/dev/null || true
  fi
}

ssh_run() {
  local host="$1"; shift
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] ssh root@${host} $*"
    return 0
  fi
  ssh -o ControlPath="${SSH_SOCKET}" "root@${host}" "$@"
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

log "Opening SSH connection to ${PROXMOX_HOST} ..."
ssh_open "$PROXMOX_HOST"

# ─── Search for existing searcher-stack deployments ───────────────────────────
# Find all containers whose hostname starts with the base name so we can show
# them before asking for a postfix.
log "Searching for existing searcher-stack containers on ${PROXMOX_HOST} ..."
EXISTING_STACKS="$(ssh_run "$PROXMOX_HOST" \
  "pct list | awk 'NR>1 {print \$1}' | while read id; do
     h=\$(pct config \$id 2>/dev/null | awk -F': ' '/^hostname:/{print \$2}')
     case \"\$h\" in ${LXC_HOSTNAME_BASE}*) echo \"\$id \$h\" ;; esac
   done" || true)"

if [[ -n "$EXISTING_STACKS" ]]; then
  echo ""
  echo "  Existing searcher-stack containers on ${PROXMOX_HOST}:"
  while IFS= read -r line; do
    echo "    VMID $(echo "$line" | awk '{print $1}')  hostname: $(echo "$line" | awk '{print $2}')"
  done <<< "$EXISTING_STACKS"
fi

# ─── Resolve hostname postfix ─────────────────────────────────────────────────
if [[ -z "$LXC_HOSTNAME_POSTFIX" ]]; then
  echo ""
  read -rp "Hostname postfix (leave blank for none, e.g. 'aev' → ${LXC_HOSTNAME_BASE}-aev): " LXC_HOSTNAME_POSTFIX
fi
if [[ -n "$LXC_HOSTNAME_POSTFIX" ]]; then
  LXC_HOSTNAME="${LXC_HOSTNAME_BASE}-${LXC_HOSTNAME_POSTFIX}"
else
  LXC_HOSTNAME="${LXC_HOSTNAME_BASE}"
fi
log "Hostname: ${LXC_HOSTNAME}"

# ─── Resolve VMID from already-fetched stack list ─────────────────────────────
# Look up the chosen hostname in EXISTING_STACKS (no second SSH call needed).
FOUND_VMID="$(echo "$EXISTING_STACKS" | awk -v h="$LXC_HOSTNAME" '$2==h{print $1}')"

if [[ -n "$FOUND_VMID" ]]; then
  log "Found existing '${LXC_HOSTNAME}' at VMID ${FOUND_VMID} — will destroy and redeploy."
  VMID="$FOUND_VMID"
else
  log "No existing '${LXC_HOSTNAME}' — finding next available VMID ..."
  NEXT_VMID="$(ssh_run "$PROXMOX_HOST" \
    "pvesh get /cluster/nextid 2>/dev/null || \
     { used=\$(pct list | awk 'NR>1{print \$1}' | sort -n); \
       id=100; for u in \$used; do [ \$id -lt \$u ] && break; id=\$((u+1)); done; echo \$id; }" \
    | tr -d '[:space:]"' || echo "")"
  if [[ "$NEXT_VMID" =~ ^[0-9]+$ ]]; then
    VMID="$NEXT_VMID"
  fi
  read -rp "VMID for new container [${VMID}]: " VMID_INPUT
  VMID="${VMID_INPUT:-${VMID}}"
  [[ "$VMID" =~ ^[0-9]+$ ]] || die "VMID must be a number."
fi

# ─── Select storage ───────────────────────────────────────────────────────────
if [[ "$STORAGE" == "local-lvm" ]]; then
  log "Querying available storage on ${PROXMOX_HOST} ..."
  STORAGE_RAW="$(ssh_run "$PROXMOX_HOST" \
    "pvesm status --content rootdir 2>/dev/null | awk 'NR>1 && \$3==\"active\" {print \$1, \$2}'" \
    || true)"

  if [[ -n "$STORAGE_RAW" ]]; then
    mapfile -t STORAGE_LIST <<< "$STORAGE_RAW"
    echo ""
    echo "Available storage pools for LXC rootfs:"
    for i in "${!STORAGE_LIST[@]}"; do
      echo "  [$i] ${STORAGE_LIST[$i]}"
    done
    echo ""
    read -rp "Select storage index [0]: " STORAGE_CHOICE
    STORAGE_CHOICE="${STORAGE_CHOICE:-0}"
    STORAGE="$(echo "${STORAGE_LIST[$STORAGE_CHOICE]}" | awk '{print $1}')"
    log "Using storage: ${STORAGE}"
  else
    log "Could not query storage — using default: ${STORAGE}"
  fi
fi

if [[ "$LXC_IP" != "dhcp" && -z "$GATEWAY" ]]; then
  read -rp "Gateway IP (required for static IP): " GATEWAY
  [[ -z "$GATEWAY" ]] && die "GATEWAY is required when using a static IP."
fi

# ─── Detect or select LXC template ───────────────────────────────────────────
log "Querying available Debian templates on ${PROXMOX_HOST} ..."
TEMPLATES_RAW="$(ssh_run "$PROXMOX_HOST" \
  "pvesm status --content vztmpl 2>/dev/null | awk 'NR>1 {print \$1}' | \
   while read storage; do
     pveam list \"\$storage\" 2>/dev/null | awk 'NR>1 {print \$1}'
   done | grep -i 'debian' | sort -rV" \
  || true)"

if [[ -z "$TEMPLATE" ]]; then
  if [[ -z "$TEMPLATES_RAW" ]]; then
    die "No Debian templates found on any storage. Download one with: pveam download local debian-12-standard_*.tar.zst"
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

# ─── Select env files ─────────────────────────────────────────────────────────
# Search for .env* files in the directory where the script is being run from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEARCH_DIR="$(pwd)"

pick_env_file() {
  local label="$1"       # e.g. "searcher"
  local varname="$2"     # variable to set with result path

  mapfile -t ENV_FILES < <(find "$SEARCH_DIR" -maxdepth 2 -name ".env*" -type f | sort)

  if [[ "${#ENV_FILES[@]}" -eq 0 ]]; then
    echo "  No .env files found in ${SEARCH_DIR} — will use .env.example from repo."
    eval "${varname}=''"
    return
  fi

  echo ""
  echo "  Available .env files for ${label}:"
  echo "    [0] (none — use .env.example from repo)"
  for i in "${!ENV_FILES[@]}"; do
    echo "    [$((i+1))] ${ENV_FILES[$i]}"
  done
  read -rp "  Select index or type a path [0]: " ENV_CHOICE
  ENV_CHOICE="${ENV_CHOICE:-0}"

  if [[ "$ENV_CHOICE" == "0" ]]; then
    eval "${varname}=''"
  elif [[ "$ENV_CHOICE" =~ ^[0-9]+$ ]]; then
    local idx=$((ENV_CHOICE - 1))
    if [[ "$idx" -ge 0 && "$idx" -lt "${#ENV_FILES[@]}" ]]; then
      eval "${varname}='${ENV_FILES[$idx]}'"
      log "Using ${ENV_FILES[$idx]} for ${label}"
    else
      echo "  Invalid index — will use .env.example from repo."
      eval "${varname}=''"
    fi
  else
    # User typed a path directly
    local expanded="${ENV_CHOICE/#\~/$HOME}"
    if [[ -f "$expanded" ]]; then
      eval "${varname}='${expanded}'"
      log "Using ${expanded} for ${label}"
    else
      echo "  File not found: ${expanded} — will use .env.example from repo."
      eval "${varname}=''"
    fi
  fi
}

echo ""
echo "Select a shared .env file to upload to all services (API keys and runtime config):"
pick_env_file "all services" SHARED_ENV_FILE

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
echo "  Shared env    : ${SHARED_ENV_FILE:-(repo .env.example for each service)}"
echo ""
echo "  Services to install:"
echo "    searcher-mcp       port ${SEARCHER_PORT}"
echo "    browser-worker     port ${WORKER_PORT}"
echo "    xvfb               virtual display :99"
echo "    chromium-display   port ${CDP_PORT} (localhost CDP) + GUI on :99"
echo "    x11vnc             VNC on port 5900"
echo "    novnc              browser VNC client port ${NOVNC_PORT}"
echo ""
if [[ "$DRY_RUN" == "1" ]]; then
  echo "  *** DRY RUN — no changes will be made ***"
  echo ""
fi
read -rp "Proceed? [Y/n] " CONFIRM
CONFIRM="${CONFIRM:-y}"
[[ "${CONFIRM,,}" == "y" ]] || { log "Aborted."; exit 0; }

# ─── Create LXC ───────────────────────────────────────────────────────────────
# Check whether the chosen VMID is already occupied (could be an unrelated container
# if the user manually specified --vmid and the hostname search found nothing).
EXISTS="$(ssh_run "$PROXMOX_HOST" "pct list | awk 'NR>1 {print \$1}' | grep -w '${VMID}' || true")"
if [[ -n "$EXISTS" ]]; then
  EXISTING_HOSTNAME="$(ssh_run "$PROXMOX_HOST" "pct config ${VMID} | awk -F': ' '/^hostname:/{print \$2}'" || echo "unknown")"
  echo ""
  if [[ "$EXISTING_HOSTNAME" != "$LXC_HOSTNAME" ]]; then
    echo "  WARNING: VMID ${VMID} is occupied by '${EXISTING_HOSTNAME}',"
    echo "           which is NOT a searcher-stack container."
    echo "           Destroying it will permanently delete an unrelated LXC."
  else
    echo "  VMID ${VMID} ('${EXISTING_HOSTNAME}') will be permanently destroyed and redeployed."
  fi
  echo ""
  read -rp "  Destroy VMID ${VMID} ('${EXISTING_HOSTNAME}')? [Y/n] " CONFIRM_DESTROY
  CONFIRM_DESTROY="${CONFIRM_DESTROY:-y}"
  [[ "${CONFIRM_DESTROY,,}" == "y" ]] || die "Aborted."
  log "Confirmed — stopping and destroying VMID ${VMID} ..."
  ssh_run "$PROXMOX_HOST" "pct stop ${VMID} --skiplock 1 2>/dev/null || true"
  ssh_run "$PROXMOX_HOST" "pct destroy ${VMID} --purge 1"
fi

NET_CONFIG="name=eth0,bridge=${BRIDGE},ip=dhcp"
if [[ "$LXC_IP" != "dhcp" ]]; then
  NET_CONFIG="name=eth0,bridge=${BRIDGE},ip=${LXC_IP},gw=${GATEWAY}"
fi

# ZFS storage requires a bare integer (GB), all others accept the G suffix.
# Use the already-queried STORAGE_LIST (from the storage selection step) to
# check the type — avoids a separate SSH call and parsing ambiguity.
DISK_SIZE_NUM="${DISK_SIZE//G/}"
ROOTFS_ARG="${STORAGE}:${DISK_SIZE}"
for entry in "${STORAGE_LIST[@]+"${STORAGE_LIST[@]}"}"; do
  name="$(echo "$entry" | awk '{print $1}')"
  stype="$(echo "$entry" | awk '{print $2}')"
  if [[ "$name" == "$STORAGE" && "$stype" == "zfspool" ]]; then
    ROOTFS_ARG="${STORAGE}:${DISK_SIZE_NUM}"
    break
  fi
done

log "Creating LXC ${VMID} (${LXC_HOSTNAME}) ..."
ssh_run "$PROXMOX_HOST" \
  "pct create ${VMID} ${TEMPLATE} \
    --hostname ${LXC_HOSTNAME} \
    --storage ${STORAGE} \
    --rootfs ${ROOTFS_ARG} \
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

# ─── Locale setup ─────────────────────────────────────────────────────────────
log "Configuring locale ..."
lxc_exec "$VMID" "
  apt-get update -qq
  apt-get install -y -qq locales
  sed -i 's/^# *en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen
  locale-gen en_US.UTF-8
  update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
"

# ─── System packages ──────────────────────────────────────────────────────────
log "Installing system packages ..."
lxc_exec "$VMID" "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv git curl chromium"

# ─── Clone repo ───────────────────────────────────────────────────────────────
log "Cloning ${REPO_URL} (branch: ${REPO_BRANCH}) ..."
lxc_exec "$VMID" "git clone --branch ${REPO_BRANCH} --depth 1 ${REPO_URL} /opt/searcher"

# ─── Upload shared env file ───────────────────────────────────────────────────
# Uploaded after clone so /opt/searcher/ exists. Each service symlinks to it.
SHARED_ENV_DEST="/opt/searcher/.env"
if [[ -n "$SHARED_ENV_FILE" && -f "$SHARED_ENV_FILE" ]]; then
  log "Uploading ${SHARED_ENV_FILE} → LXC:${SHARED_ENV_DEST} ..."
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] scp ${SHARED_ENV_FILE} → LXC:${SHARED_ENV_DEST}"
  else
    tmp_remote="$(ssh_run "$PROXMOX_HOST" "mktemp")"
    scp -o ControlPath="${SSH_SOCKET}" "$SHARED_ENV_FILE" "root@${PROXMOX_HOST}:${tmp_remote}"
    ssh_run "$PROXMOX_HOST" "pct push ${VMID} ${tmp_remote} ${SHARED_ENV_DEST} --perms 0600 && rm -f ${tmp_remote}"
  fi
  log "Shared env uploaded."
fi

# ─── Inject ROOT_PATH vars based on hostname postfix ─────────────────────────
# If a postfix is set (e.g. "aev"), configure path prefixes so Nginx can route
# multiple users under the same domain: /aev/search/ and /aev/browser/
if [[ -n "$LXC_HOSTNAME_POSTFIX" ]]; then
  SEARCHER_ROOT_PATH="/${LXC_HOSTNAME_POSTFIX}/search"
  BROWSER_ROOT_PATH="/${LXC_HOSTNAME_POSTFIX}/browser"
  log "Setting root paths: SEARCHER_ROOT_PATH=${SEARCHER_ROOT_PATH}  BROWSER_ROOT_PATH=${BROWSER_ROOT_PATH}"
  lxc_exec "$VMID" "
    grep -q 'SEARCHER_ROOT_PATH' /opt/searcher/.env && \
      sed -i 's|^SEARCHER_ROOT_PATH=.*|SEARCHER_ROOT_PATH=${SEARCHER_ROOT_PATH}|' /opt/searcher/.env || \
      echo 'SEARCHER_ROOT_PATH=${SEARCHER_ROOT_PATH}' >> /opt/searcher/.env
    grep -q 'BROWSER_ROOT_PATH' /opt/searcher/.env && \
      sed -i 's|^BROWSER_ROOT_PATH=.*|BROWSER_ROOT_PATH=${BROWSER_ROOT_PATH}|' /opt/searcher/.env || \
      echo 'BROWSER_ROOT_PATH=${BROWSER_ROOT_PATH}' >> /opt/searcher/.env
  "
fi

# ─── Install searcher ─────────────────────────────────────────────────────────
log "Installing searcher ..."
lxc_exec "$VMID" "
  cd /opt/searcher/searcher
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
  if [ -f /opt/searcher/.env ]; then ln -sf /opt/searcher/.env /opt/searcher/searcher/.env; else cp /opt/searcher/.env.example /opt/searcher/.env && ln -sf /opt/searcher/.env /opt/searcher/searcher/.env; fi
  cp /opt/searcher/searcher/deploy/searcher-mcp.service /etc/systemd/system/searcher-mcp.service
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
  cd /opt/searcher/browser_worker
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
"

log "Installing Playwright Chromium ..."
lxc_exec "$VMID" "
  cd /opt/searcher/browser_worker
  DEBIAN_FRONTEND=noninteractive .venv/bin/python -m playwright install-deps chromium 2>&1 | tail -5
  .venv/bin/python -m playwright install chromium 2>&1 | tail -5
"

# ─── Install display stack (Xvfb + Chromium GUI + x11vnc + noVNC) ────────────
log "Installing display and VNC packages ..."
lxc_exec "$VMID" "
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    xvfb x11vnc novnc websockify xauth dbus-x11
"

log "Installing display/VNC/noVNC systemd services ..."
lxc_exec "$VMID" "
  mkdir -p /opt/searcher/browser_worker/chromium-profile

  cp /opt/searcher/browser_worker/deploy/xvfb.service            /etc/systemd/system/xvfb.service
  cp /opt/searcher/browser_worker/deploy/x11vnc.service          /etc/systemd/system/x11vnc.service
  cp /opt/searcher/browser_worker/deploy/chromium-display.service /etc/systemd/system/chromium-display.service
  cp /opt/searcher/browser_worker/deploy/novnc.service           /etc/systemd/system/novnc.service

  systemctl daemon-reload
  systemctl enable xvfb x11vnc chromium-display novnc
  systemctl start xvfb
  sleep 2
  systemctl start x11vnc
  sleep 1
  systemctl start chromium-display
  sleep 3
  systemctl start novnc
"

log "Waiting for Chromium CDP on port ${CDP_PORT} ..."
lxc_exec "$VMID" "
  for i in \$(seq 1 15); do
    curl -sf http://127.0.0.1:${CDP_PORT}/json/version > /dev/null && exit 0
    sleep 2
  done
  echo 'chromium-display did not start in time'; exit 1
"
log "chromium-display PASSED."

log "Waiting for noVNC on port ${NOVNC_PORT} ..."
lxc_exec "$VMID" "
  for i in \$(seq 1 10); do
    curl -sf http://127.0.0.1:${NOVNC_PORT}/ > /dev/null && exit 0
    sleep 2
  done
  echo 'noVNC did not start in time'; exit 1
"
log "noVNC PASSED."

# ─── Start browser-worker ─────────────────────────────────────────────────────
log "Configuring and starting browser-worker ..."
lxc_exec "$VMID" "
  ln -sf /opt/searcher/.env /opt/searcher/browser_worker/.env
  cp /opt/searcher/browser_worker/deploy/browser-worker.service /etc/systemd/system/browser-worker.service
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
echo "  noVNC           http://${LXC_ACTUAL_IP}:${NOVNC_PORT}/vnc.html"
if [[ -n "$LXC_HOSTNAME_POSTFIX" ]]; then
  echo ""
  echo "  Nginx proxy paths (configure in Nginx Proxy Manager):"
  echo "    /${LXC_HOSTNAME_POSTFIX}/search/  →  http://${LXC_ACTUAL_IP}:${SEARCHER_PORT}/"
  echo "    /${LXC_HOSTNAME_POSTFIX}/browser/ →  http://${LXC_ACTUAL_IP}:${WORKER_PORT}/"
  echo ""
  echo "  MCP endpoints (after Nginx setup):"
  echo "    https://<domain>/${LXC_HOSTNAME_POSTFIX}/search/mcp"
  echo "    https://<domain>/${LXC_HOSTNAME_POSTFIX}/browser/mcp"
fi
echo ""
echo "  Next steps:"
if [[ -z "$SHARED_ENV_FILE" ]]; then
  echo "    1. Add API keys to /opt/searcher/.env on VMID ${VMID},"
  echo "       then: pct exec ${VMID} -- bash /opt/searcher/deploy/restart.sh"
else
  echo "    1. Shared env uploaded from ${SHARED_ENV_FILE} — API keys are set."
fi
echo ""
echo "    2. To log into publisher portals (ScienceDirect, IEEE, etc.):"
echo "       Open http://${LXC_ACTUAL_IP}:${NOVNC_PORT}/vnc.html"
echo "       Enter your VNC password, then log in to the portal in the browser."
echo "       Session saves to /opt/searcher/browser_worker/chromium-profile — persists across restarts."

# ─── Optional Tailscale install ───────────────────────────────────────────────
echo ""
read -rp "Install Tailscale on VMID ${VMID}? [Y/n] " INSTALL_TAILSCALE
INSTALL_TAILSCALE="${INSTALL_TAILSCALE:-y}"
if [[ "${INSTALL_TAILSCALE,,}" == "y" ]]; then
  log "Installing Tailscale on VMID ${VMID} ..."
  ssh_run "$PROXMOX_HOST" \
    "bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/tools/addon/add-tailscale-lxc.sh)\" -- ${VMID}"
  log "Tailscale install complete."
fi
