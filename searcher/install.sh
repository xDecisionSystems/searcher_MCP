#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/searcher"
SERVICE_NAME="searcher-mcp"
SERVICE_FILE="${SERVICE_NAME}.service"
BASE_URL="${SEARCHER_BASE_URL:-${SEARCHER_MCP_BASE_URL:-https://raw.githubusercontent.com/xDecisionSystems/searcher_MCP/main/searcher}}"

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
mkdir -p "${APP_DIR}/deploy" "${APP_DIR}/searcher_mcp/services"

download_file() {
  local src="$1"
  local dst="$2"
  echo "Downloading ${src} -> ${dst}"
  mkdir -p "$(dirname "${dst}")"
  wget -qO "${dst}" "${BASE_URL}/${src}"
}

read_version_name() {
  local version_file="$1"
  if [[ ! -f "${version_file}" ]]; then
    echo "unknown"
    return
  fi
  local version_name
  version_name="$(grep -E '^VERSION_NAME=' "${version_file}" | head -n1 | cut -d'=' -f2- || true)"
  version_name="${version_name%\"}"
  version_name="${version_name#\"}"
  version_name="${version_name%\'}"
  version_name="${version_name#\'}"
  if [[ -z "${version_name}" ]]; then
    echo "unknown"
  else
    echo "${version_name}"
  fi
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
  "searcher_mcp/__init__.py"
  "searcher_mcp/api.py"
  "searcher_mcp/config.py"
  "searcher_mcp/http_client.py"
  "searcher_mcp/utils.py"
  "searcher_mcp/services/__init__.py"
  "searcher_mcp/services/search.py"
  "searcher_mcp/services/page.py"
  "searcher_mcp/services/pdf.py"
)
for rel_path in "${DOWNLOAD_FILES[@]}"; do
  download_file "${rel_path}" "${APP_DIR}/${rel_path}"
done
chmod +x "${APP_DIR}/install.sh" "${APP_DIR}/update.sh"
VERSION_NAME="$(read_version_name "${APP_DIR}/VERSION.md")"
echo "Installing Searcher MCP version: ${VERSION_NAME}"

echo "[4/8] Creating virtual environment..."
if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
  python3 -m venv "${APP_DIR}/.venv"
fi

echo "[5/8] Installing Python dependencies..."
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/.venv/bin/python" -m pip install -r "${APP_DIR}/requirements.txt"

echo "[6/8] Ensuring environment file exists..."
if [[ ! -f "${APP_DIR}/.env" ]]; then
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  echo "Created ${APP_DIR}/.env from template. Edit it with your API keys."
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
echo "Swagger docs: http://<lxc-ip>:8000/docs"
