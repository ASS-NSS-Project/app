#!/usr/bin/env bash
# Check knowledge base stats + latest documents.
# Usage:
#   ./02_check_knowledge_base.sh

#   export API_URL=https://webrag.nss.jkzl.eu
#   export ADMIN_EMAIL=admin 
#   export ADMIN_PASSWORD=secret 
#   export SOURCE_ID=<uuid>
#   ./02_check_knowledge_base.sh

set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
LIMIT="${LIMIT:-20}"
OFFSET="${OFFSET:-0}"
SOURCE_ID="${SOURCE_ID:-}"

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

if [[ -n "$SOURCE_ID" ]]; then
  STATS_PATH="/documents/stats?source_id=${SOURCE_ID}"
  DOCS_PATH="/documents/?source_id=${SOURCE_ID}&limit=${LIMIT}&offset=${OFFSET}"
else
  STATS_PATH="/documents/stats"
  DOCS_PATH="/documents/?limit=${LIMIT}&offset=${OFFSET}"
fi

echo "=== Knowledge Base Stats ==="
curl -sf "${API_URL}${STATS_PATH}" \
  -H "Authorization: Bearer ${TOKEN}" | jq .
echo
echo "=== Documents ==="
curl -sf "${API_URL}${DOCS_PATH}" \
  -H "Authorization: Bearer ${TOKEN}" | jq . 
echo
