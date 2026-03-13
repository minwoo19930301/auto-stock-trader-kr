#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
STATE_FILE="${PROJECT_ROOT}/.deploy/oracle/instance.json"
REMOTE_USER="${REMOTE_USER:-opc}"
REMOTE_DIR="${REMOTE_DIR:-/opt/stock-broker-onboarding}"
SSH_KEY_PATH="${SSH_KEY_PATH:-$HOME/.ssh/id_rsa}"

if [[ ! -f "${STATE_FILE}" ]]; then
  echo "state file not found: ${STATE_FILE}" >&2
  exit 1
fi

PUBLIC_IP="$(python3 - <<'PY' "${STATE_FILE}"
import json, sys
with open(sys.argv[1]) as fp:
    data = json.load(fp)
print(data.get("public_ip") or "")
PY
)"

if [[ -z "${PUBLIC_IP}" ]]; then
  echo "public_ip missing in ${STATE_FILE}" >&2
  exit 1
fi

echo "Deploying to ${REMOTE_USER}@${PUBLIC_IP}:${REMOTE_DIR}"

ssh -i "${SSH_KEY_PATH}" -o StrictHostKeyChecking=accept-new "${REMOTE_USER}@${PUBLIC_IP}" "sudo mkdir -p /opt && sudo chown ${REMOTE_USER}:${REMOTE_USER} /opt"
rsync -av --delete \
  --exclude '.git/' \
  --exclude '.tools/' \
  --exclude '.deploy/' \
  --exclude 'backend/.venv/' \
  -e "ssh -i ${SSH_KEY_PATH} -o StrictHostKeyChecking=accept-new" \
  "${PROJECT_ROOT}/" "${REMOTE_USER}@${PUBLIC_IP}:${REMOTE_DIR}/"

ssh -i "${SSH_KEY_PATH}" -o StrictHostKeyChecking=accept-new "${REMOTE_USER}@${PUBLIC_IP}" "cd ${REMOTE_DIR} && chmod +x infra/oracle/scripts/bootstrap_oracle_ubuntu.sh && APP_USER=${REMOTE_USER} SERVER_NAME=${PUBLIC_IP} ./infra/oracle/scripts/bootstrap_oracle_ubuntu.sh"

echo "Done. Public health check: http://${PUBLIC_IP}/healthz"
