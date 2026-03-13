#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
TEMPLATE_PATH="${PROJECT_ROOT}/infra/oracle/templates/cloud-init-stock-broker.yaml.tpl"
OUTPUT_PATH="${OCI_CLOUD_INIT_OUTPUT:-${PROJECT_ROOT}/.deploy/oracle/cloud-init.yaml}"
APP_USER="${OCI_APP_USER:-opc}"
BUNDLE_URL="${OCI_BUNDLE_URL:-}"
REPO_URL="${OCI_REPO_URL:-https://github.com/minwoo19930301/auto-stock-trader-kr.git}"
REPO_BRANCH="${OCI_REPO_BRANCH:-main}"
APP_DOMAIN="${OCI_APP_DOMAIN:-}"

if [[ -z "${BUNDLE_URL}" ]]; then
  echo "OCI_BUNDLE_URL is required" >&2
  exit 1
fi

mkdir -p "$(dirname "${OUTPUT_PATH}")"

sed \
  -e "s|__APP_USER__|${APP_USER}|g" \
  -e "s|__BUNDLE_URL__|${BUNDLE_URL}|g" \
  -e "s|__REPO_URL__|${REPO_URL}|g" \
  -e "s|__REPO_BRANCH__|${REPO_BRANCH}|g" \
  -e "s|__APP_DOMAIN__|${APP_DOMAIN}|g" \
  "${TEMPLATE_PATH}" > "${OUTPUT_PATH}"

echo "${OUTPUT_PATH}"
