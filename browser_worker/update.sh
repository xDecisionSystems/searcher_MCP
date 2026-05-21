#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/browser_worker"
SERVICE_NAME="browser-worker"
SERVICE_FILE="${SERVICE_NAME}.service"
BASE_URL="${BROWSER_WORKER_BASE_URL:-https://raw.githubusercontent.com/xDecisionSystems/searcher_MCP/main/browser_worker}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run update.sh as root (or with sudo)."
  exit 1
fi

mkdir -p "${APP_DIR}/deploy" "${APP_DIR}/browser_worker/services"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

download_file() {
  local src="$1"
  local dst="$2"
  mkdir -p "$(dirname "${dst}")"
  wget -qO "${dst}" "${BASE_URL}/${src}"
}

echo "[1/6] Downloading latest service files..."
DOWNLOAD_FILES=(
  "app.py"
  "requirements.txt"
  ".env.example"
  "VERSION.md"
  "deploy/${SERVICE_FILE}"
  "install.sh"
  "update.sh"
  "browser_worker/__init__.py"
  "browser_worker/api.py"
  "browser_worker/config.py"
  "browser_worker/services/__init__.py"
  "browser_worker/services/download.py"
)
for rel_path in "${DOWNLOAD_FILES[@]}"; do
  download_file "${rel_path}" "${TMP_DIR}/${rel_path}"
done

echo "[2/6] Updating local files..."
for rel_path in "${DOWNLOAD_FILES[@]}"; do
  src_path="${TMP_DIR}/${rel_path}"
  dst_path="${APP_DIR}/${rel_path}"
  mkdir -p "$(dirname "${dst_path}")"
  file_mode="0644"
  case "${rel_path}" in
    install.sh|update.sh) file_mode="0755" ;;
  esac
  install -m "${file_mode}" "${src_path}" "${dst_path}"
done

echo "[3/6] Ensuring virtual environment exists..."
if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
  python3 -m venv "${APP_DIR}/.venv"
fi

echo "[4/6] Installing/updating Python dependencies..."
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/.venv/bin/python" -m pip install -r "${APP_DIR}/requirements.txt"
"${APP_DIR}/.venv/bin/python" -m playwright install chromium

echo "[5/6] Refreshing systemd unit..."
cp "${APP_DIR}/deploy/${SERVICE_FILE}" "/etc/systemd/system/${SERVICE_FILE}"
systemctl daemon-reload

echo "[6/6] Restarting service..."
systemctl restart "${SERVICE_NAME}"
systemctl --no-pager --full status "${SERVICE_NAME}" || true

echo
echo "Update complete."
echo "Base URL used: ${BASE_URL}"
