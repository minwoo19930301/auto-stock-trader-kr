#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
STATE_FILE="${PROJECT_ROOT}/.deploy/oracle/instance.json"

APP_DOMAIN="${APP_DOMAIN:-${1:-}}"
REMOTE_USER="${REMOTE_USER:-}"
SSH_KEY_PATH="${SSH_KEY_PATH:-$HOME/.ssh/id_rsa}"

if [[ -z "${APP_DOMAIN}" ]]; then
  echo "Usage: APP_DOMAIN=app.example.com $0" >&2
  echo "or:    $0 app.example.com" >&2
  exit 1
fi

if [[ ! -f "${STATE_FILE}" ]]; then
  echo "state file not found: ${STATE_FILE}" >&2
  exit 1
fi

PUBLIC_IP="$(python3 - <<'PY' "${STATE_FILE}"
import json,sys
with open(sys.argv[1], encoding="utf-8") as fp:
    print((json.load(fp).get("public_ip") or "").strip())
PY
)"

if [[ -z "${PUBLIC_IP}" ]]; then
  echo "public_ip missing in ${STATE_FILE}" >&2
  exit 1
fi

if [[ -z "${REMOTE_USER}" ]]; then
  for candidate in ubuntu opc ec2-user; do
    if ssh -i "${SSH_KEY_PATH}" -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=5 "${candidate}@${PUBLIC_IP}" "true" >/dev/null 2>&1; then
      REMOTE_USER="${candidate}"
      break
    fi
  done
fi

if [[ -z "${REMOTE_USER}" ]]; then
  echo "failed to detect remote user; set REMOTE_USER explicitly" >&2
  exit 1
fi

ssh -i "${SSH_KEY_PATH}" -o StrictHostKeyChecking=accept-new "${REMOTE_USER}@${PUBLIC_IP}" \
  "sudo mkdir -p /etc/stock-broker-onboarding && \
   echo '${APP_DOMAIN}' | sudo tee /etc/stock-broker-onboarding/domain.txt >/dev/null && \
   printf 'APP_BASE_URL=https://${APP_DOMAIN}\n' | sudo tee /etc/stock-broker-onboarding/app.env >/dev/null && \
   sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
${APP_DOMAIN} {
  encode gzip
  reverse_proxy 127.0.0.1:8080
}
EOF
   sudo systemctl restart caddy && \
   sudo systemctl restart stock-broker-onboarding.service"

echo "Domain updated: https://${APP_DOMAIN}"
