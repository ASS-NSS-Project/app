#!/usr/bin/env bash
# List sources via API.
# Usage:
#   ./03_list_sources.sh

#   export API_URL=https://webrag.nss.jkzl.eu
#   export ADMIN_EMAIL=admin 
#   export ADMIN_PASSWORD=secret 
#   ./03_list_sources.sh

set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
LIMIT="${LIMIT:-100}"
OFFSET="${OFFSET:-0}"

if [[ -z "$ADMIN_PASSWORD" ]]; then
  read -rsp "Admin password: " ADMIN_PASSWORD
  echo
fi

TOKEN=$(curl -sf -X POST "${API_URL}/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=${ADMIN_EMAIL}&password=${ADMIN_PASSWORD}" \
  | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: login failed" >&2
  exit 1
fi

echo "=== Currently present sources ==="
curl -sf "${API_URL}/sources/?limit=${LIMIT}&offset=${OFFSET}" \
  -H "Authorization: Bearer ${TOKEN}" | jq .
