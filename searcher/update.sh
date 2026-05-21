#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/searcher"
SERVICE_NAME="searcher-mcp"
SERVICE_FILE="${SERVICE_NAME}.service"
BASE_URL="${SEARCHER_BASE_URL:-${SEARCHER_MCP_BASE_URL:-https://raw.githubusercontent.com/xDecisionSystems/searcher_MCP/main/searcher}}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run update.sh as root (or with sudo)."
  exit 1
fi

mkdir -p "${APP_DIR}/deploy" "${APP_DIR}/searcher_mcp/services"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

download_file() {
  local src="$1"
  local dst="$2"
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

echo "[1/6] Downloading latest service files..."
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
  download_file "${rel_path}" "${TMP_DIR}/${rel_path}"
done

CURRENT_VERSION_NAME="$(read_version_name "${APP_DIR}/VERSION.md")"
NEW_VERSION_NAME="$(read_version_name "${TMP_DIR}/VERSION.md")"
echo "Current version: ${CURRENT_VERSION_NAME}"
echo "New version:     ${NEW_VERSION_NAME}"
read -r -p "Proceed with update? [Y/n] " CONFIRM_UPDATE
CONFIRM_UPDATE="${CONFIRM_UPDATE:-Y}"
case "${CONFIRM_UPDATE}" in
  [Yy]|[Yy][Ee][Ss]) ;;
  [Nn]|[Nn][Oo])
    echo "Update canceled by user."
    exit 0
    ;;
  *)
    echo "Unrecognized response. Defaulting to Yes."
    ;;
esac

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

echo "[5/6] Refreshing systemd unit..."
cp "${APP_DIR}/deploy/${SERVICE_FILE}" "/etc/systemd/system/${SERVICE_FILE}"
systemctl daemon-reload

echo "[6/6] Restarting service..."
systemctl restart "${SERVICE_NAME}"
systemctl --no-pager --full status "${SERVICE_NAME}" || true

echo
echo "Update complete."
echo "Base URL used: ${BASE_URL}"
