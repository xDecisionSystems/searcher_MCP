#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/browser_worker"
SERVICE_NAME="browser-worker"
SERVICE_FILE="${SERVICE_NAME}.service"
BASE_URL="${BROWSER_WORKER_BASE_URL:-https://raw.githubusercontent.com/xDecisionSystems/searcher_MCP/main/browser_worker}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run install.sh as root (or with sudo)."
  exit 1
fi

echo "[1/8] Installing system dependencies (including curl)..."
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  wget \
  python3 \
  python3-venv \
  python3-pip

echo "[2/8] Preparing application directories..."
mkdir -p "${APP_DIR}/deploy" "${APP_DIR}/browser_worker/services"

download_file() {
  local src="$1"
  local dst="$2"
  echo "Downloading ${src} -> ${dst}"
  mkdir -p "$(dirname "${dst}")"
  wget -qO "${dst}" "${BASE_URL}/${src}"
}

echo "[3/8] Downloading application files..."
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
  download_file "${rel_path}" "${APP_DIR}/${rel_path}"
done
chmod +x "${APP_DIR}/install.sh" "${APP_DIR}/update.sh"

echo "[4/8] Creating virtual environment..."
if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
  python3 -m venv "${APP_DIR}/.venv"
fi

echo "[5/8] Installing Python dependencies..."
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/.venv/bin/python" -m pip install -r "${APP_DIR}/requirements.txt"
"${APP_DIR}/.venv/bin/python" -m playwright install chromium

echo "[6/8] Ensuring environment file exists..."
if [[ ! -f "${APP_DIR}/.env" ]]; then
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  echo "Created ${APP_DIR}/.env from template. Edit it as needed."
fi

echo "[7/8] Installing systemd service..."
cp "${APP_DIR}/deploy/${SERVICE_FILE}" "/etc/systemd/system/${SERVICE_FILE}"
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"

echo "[8/8] Verifying service status..."
systemctl restart "${SERVICE_NAME}"
systemctl --no-pager --full status "${SERVICE_NAME}" || true

echo
echo "Install complete."
echo "Base URL used: ${BASE_URL}"
echo "Service: ${SERVICE_NAME}"
echo "App directory: ${APP_DIR}"
echo "Swagger docs: http://<worker-ip>:8010/docs"
