#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
OCI_BIN="${OCI_BIN:-${PROJECT_ROOT}/.tools/oci-cli/bin/oci}"
TENANCY_ID="${OCI_TENANCY_ID:-$(awk -F= '/^tenancy=/{print $2}' "${HOME}/.oci/config")}"
REGION="${OCI_REGION:-$(awk -F= '/^region=/{print $2}' "${HOME}/.oci/config")}"
BUCKET_NAME="${OCI_DEPLOY_BUCKET_NAME:-stock-broker-onboarding-deploy}"
STATE_DIR="${PROJECT_ROOT}/.deploy/oracle"
TIMESTAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
BUNDLE_NAME="${OCI_BUNDLE_NAME:-stock-broker-onboarding-${TIMESTAMP}.tar.gz}"
BUNDLE_PATH="${STATE_DIR}/${BUNDLE_NAME}"
PAR_NAME="stock-broker-deploy-${TIMESTAMP}"

mkdir -p "${STATE_DIR}"

if [[ ! -x "${OCI_BIN}" ]]; then
  echo "OCI CLI not found at ${OCI_BIN}" >&2
  exit 1
fi

tar \
  --exclude='.git' \
  --exclude='.tools' \
  --exclude='.deploy' \
  --exclude='backend/.venv' \
  --exclude='__pycache__' \
  -czf "${BUNDLE_PATH}" \
  -C "${PROJECT_ROOT}" .

NAMESPACE="$("${OCI_BIN}" os ns get --query 'data' --raw-output)"

if ! "${OCI_BIN}" os bucket get --namespace "${NAMESPACE}" --name "${BUCKET_NAME}" >/dev/null 2>&1; then
  "${OCI_BIN}" os bucket create \
    --namespace "${NAMESPACE}" \
    --compartment-id "${TENANCY_ID}" \
    --name "${BUCKET_NAME}" >/dev/null
fi

"${OCI_BIN}" os object put \
  --namespace "${NAMESPACE}" \
  --bucket-name "${BUCKET_NAME}" \
  --name "${BUNDLE_NAME}" \
  --file "${BUNDLE_PATH}" \
  --force >/dev/null

EXPIRY="$(python3 - <<'PY'
from datetime import datetime, timedelta, timezone
print((datetime.now(timezone.utc) + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
)"

PAR_JSON="$("${OCI_BIN}" os preauth-request create \
  --namespace "${NAMESPACE}" \
  --bucket-name "${BUCKET_NAME}" \
  --name "${PAR_NAME}" \
  --access-type ObjectRead \
  --object-name "${BUNDLE_NAME}" \
  --time-expires "${EXPIRY}")"

ACCESS_URI="$(python3 - <<'PY' "${PAR_JSON}"
import json
import sys
print(json.loads(sys.argv[1])["data"]["access-uri"])
PY
)"

BUNDLE_URL="https://objectstorage.${REGION}.oraclecloud.com${ACCESS_URI}"
OUTPUT_JSON="${STATE_DIR}/bundle.json"

python3 - <<'PY' "${OUTPUT_JSON}" "${NAMESPACE}" "${BUCKET_NAME}" "${BUNDLE_NAME}" "${BUNDLE_PATH}" "${BUNDLE_URL}" "${EXPIRY}"
import json
import sys
output_path, namespace, bucket_name, bundle_name, bundle_path, bundle_url, expiry = sys.argv[1:]
payload = {
    "namespace": namespace,
    "bucket_name": bucket_name,
    "bundle_name": bundle_name,
    "bundle_path": bundle_path,
    "bundle_url": bundle_url,
    "expires_at": expiry,
}
with open(output_path, "w") as fp:
    json.dump(payload, fp, indent=2)
print(json.dumps(payload, indent=2))
PY
