#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
STATE_FILE="${PROJECT_ROOT}/.deploy/oracle/instance.json"

CF_API_TOKEN="${CF_API_TOKEN:-}"
CF_ZONE_ID="${CF_ZONE_ID:-}"
CF_RECORD_NAME="${CF_RECORD_NAME:-}"
CF_TTL="${CF_TTL:-120}"
CF_PROXIED="${CF_PROXIED:-false}"
CF_ORIGIN_IP="${CF_ORIGIN_IP:-}"

if [[ -z "${CF_API_TOKEN}" || -z "${CF_ZONE_ID}" || -z "${CF_RECORD_NAME}" ]]; then
  echo "CF_API_TOKEN, CF_ZONE_ID, CF_RECORD_NAME are required." >&2
  exit 1
fi

if [[ -z "${CF_ORIGIN_IP}" && -f "${STATE_FILE}" ]]; then
  CF_ORIGIN_IP="$(python3 - <<'PY' "${STATE_FILE}"
import json,sys
with open(sys.argv[1], encoding="utf-8") as fp:
    print((json.load(fp).get("public_ip") or "").strip())
PY
)"
fi

if [[ -z "${CF_ORIGIN_IP}" ]]; then
  echo "CF_ORIGIN_IP is required when no state file public_ip is available." >&2
  exit 1
fi

if [[ "${CF_PROXIED}" != "true" && "${CF_PROXIED}" != "false" ]]; then
  echo "CF_PROXIED must be 'true' or 'false'." >&2
  exit 1
fi

api() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  if [[ -n "${body}" ]]; then
    curl -fsS \
      -X "${method}" \
      "https://api.cloudflare.com/client/v4${path}" \
      -H "Authorization: Bearer ${CF_API_TOKEN}" \
      -H "Content-Type: application/json" \
      --data "${body}"
  else
    curl -fsS \
      -X "${method}" \
      "https://api.cloudflare.com/client/v4${path}" \
      -H "Authorization: Bearer ${CF_API_TOKEN}" \
      -H "Content-Type: application/json"
  fi
}

lookup_payload="$(curl -fsS -G "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/dns_records" \
  -H "Authorization: Bearer ${CF_API_TOKEN}" \
  --data-urlencode "type=A" \
  --data-urlencode "name=${CF_RECORD_NAME}")"

record_id="$(python3 - <<'PY' "${lookup_payload}"
import json,sys
payload=json.loads(sys.argv[1])
if not payload.get("success"):
    raise SystemExit("Cloudflare lookup failed")
rows=payload.get("result") or []
print(rows[0]["id"] if rows else "")
PY
)"

request_body="$(python3 - <<'PY' "${CF_RECORD_NAME}" "${CF_ORIGIN_IP}" "${CF_TTL}" "${CF_PROXIED}"
import json,sys
name,ip,ttl,proxied=sys.argv[1:]
print(json.dumps({
  "type":"A",
  "name":name,
  "content":ip,
  "ttl":int(ttl),
  "proxied": proxied == "true",
}))
PY
)"

if [[ -n "${record_id}" ]]; then
  response="$(api PUT "/zones/${CF_ZONE_ID}/dns_records/${record_id}" "${request_body}")"
else
  response="$(api POST "/zones/${CF_ZONE_ID}/dns_records" "${request_body}")"
fi

python3 - <<'PY' "${response}" "${CF_RECORD_NAME}" "${CF_ORIGIN_IP}"
import json,sys
payload=json.loads(sys.argv[1])
if not payload.get("success"):
    raise SystemExit(f"Cloudflare upsert failed: {payload}")
result=payload.get("result", {})
print(json.dumps({
    "record_name": result.get("name", sys.argv[2]),
    "record_content": result.get("content", sys.argv[3]),
    "proxied": result.get("proxied"),
    "ttl": result.get("ttl"),
    "id": result.get("id"),
}, indent=2))
PY
