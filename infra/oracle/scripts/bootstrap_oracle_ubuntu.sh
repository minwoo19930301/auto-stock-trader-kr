#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_ROOT="${PROJECT_ROOT}/backend"
TEMPLATE_ROOT="${PROJECT_ROOT}/infra/oracle/templates"

APP_USER="${APP_USER:-$USER}"
APP_GROUP="${APP_GROUP:-$USER}"
APP_PORT="${APP_PORT:-8000}"
SERVER_NAME="${SERVER_NAME:-_}"
ENV_FILE_PATH="${ENV_FILE_PATH:-/etc/stock-broker-onboarding/api.env}"
SYSTEMD_PATH="/etc/systemd/system/stock-broker-onboarding-api.service"
NGINX_PATH=""
NGINX_ENABLED_PATH=""
PUBLIC_HOST="${SERVER_NAME}"

if [[ "${PUBLIC_HOST}" == "_" ]]; then
  PUBLIC_HOST="<PUBLIC_IP_OR_DOMAIN>"
fi

if [[ ! -d "${BACKEND_ROOT}" ]]; then
  echo "backend directory not found: ${BACKEND_ROOT}" >&2
  exit 1
fi

echo "[1/7] install apt packages"
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv python3-pip nginx rsync
  NGINX_PATH="/etc/nginx/sites-available/stock-broker-onboarding"
  NGINX_ENABLED_PATH="/etc/nginx/sites-enabled/stock-broker-onboarding"
elif command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y python3 python3-pip nginx rsync
  NGINX_PATH="/etc/nginx/conf.d/stock-broker-onboarding.conf"
else
  echo "Unsupported package manager" >&2
  exit 1
fi

echo "[2/7] create virtual environment"
cd "${BACKEND_ROOT}"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "[3/7] ensure env file exists"
sudo install -d -m 755 /etc/stock-broker-onboarding
if [[ ! -f "${ENV_FILE_PATH}" ]]; then
  sudo install -m 640 "${BACKEND_ROOT}/.env.example" "${ENV_FILE_PATH}"
fi

echo "[4/7] render systemd service"
sed \
  -e "s|__APP_USER__|${APP_USER}|g" \
  -e "s|__APP_GROUP__|${APP_GROUP}|g" \
  -e "s|__API_ROOT__|${BACKEND_ROOT}|g" \
  -e "s|__ENV_FILE__|${ENV_FILE_PATH}|g" \
  -e "s|__VENV_BIN__|${BACKEND_ROOT}/.venv/bin|g" \
  -e "s|__APP_PORT__|${APP_PORT}|g" \
  "${TEMPLATE_ROOT}/stock-broker-onboarding-api.service.tpl" | sudo tee "${SYSTEMD_PATH}" >/dev/null

echo "[5/7] render nginx site"
if [[ -n "${NGINX_ENABLED_PATH}" ]]; then
  sudo install -d -m 755 /etc/nginx/sites-available /etc/nginx/sites-enabled
fi

sed \
  -e "s|__SERVER_NAME__|${SERVER_NAME}|g" \
  -e "s|__APP_PORT__|${APP_PORT}|g" \
  "${TEMPLATE_ROOT}/nginx-stock-broker-onboarding.conf.tpl" | sudo tee "${NGINX_PATH}" >/dev/null

if [[ -n "${NGINX_ENABLED_PATH}" ]]; then
  sudo ln -sf "${NGINX_PATH}" "${NGINX_ENABLED_PATH}"
fi

if [[ -f /etc/nginx/sites-enabled/default ]]; then
  sudo rm -f /etc/nginx/sites-enabled/default
fi

echo "[6/7] validate nginx"
sudo nginx -t

echo "[7/7] enable and start services"
sudo systemctl daemon-reload
sudo systemctl enable stock-broker-onboarding-api
sudo systemctl restart stock-broker-onboarding-api
sudo systemctl enable nginx
sudo systemctl restart nginx

if command -v firewall-cmd >/dev/null 2>&1 && sudo systemctl is-active --quiet firewalld; then
  sudo firewall-cmd --permanent --add-service=http
  sudo firewall-cmd --permanent --add-service=https
  sudo firewall-cmd --reload
fi

echo "deployment complete"
echo "health: http://127.0.0.1:${APP_PORT}/healthz"
echo "public: http://${PUBLIC_HOST}/healthz"
