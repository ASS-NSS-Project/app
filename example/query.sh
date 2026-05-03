#!/usr/bin/env bash
# Run a query against /query.
# Usage:
#   ./query.sh 

#   export API_URL=https://rag.nss.jkzl.eu 
#   export ADMIN_EMAIL=admin 
#   export ADMIN_PASSWORD=secret 
#   ./query.sh "What is Terraform?"

#   MODE=no_rag TOP_K=3 STRICT_GROUNDING=false ./query.sh "Who is rector at MENDELU?"

set -euo pipefail

QUESTION="${1:-}"
if [[ -z "$QUESTION" ]]; then
  echo "Usage: $0 \"<question>\"" >&2
  exit 1
fi

API_URL="${API_URL:-http://localhost:8000}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
MODE="${MODE:-rag}"
TOP_K="${TOP_K:-5}"
STRICT_GROUNDING="${STRICT_GROUNDING:-true}"
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
  BODY=$(printf '{"question":"%s","mode":"%s","top_k":%s,"strict_grounding":%s,"source_id":"%s"}' \
    "$QUESTION" "$MODE" "$TOP_K" "$STRICT_GROUNDING" "$SOURCE_ID")
else
  BODY=$(printf '{"question":"%s","mode":"%s","top_k":%s,"strict_grounding":%s}' \
    "$QUESTION" "$MODE" "$TOP_K" "$STRICT_GROUNDING")
fi

curl -sf -X POST "${API_URL}/query/" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "$BODY"
echo
