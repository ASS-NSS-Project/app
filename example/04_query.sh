#!/usr/bin/env bash
# Run a query against /query.
# Usage:
#   ./04_query.sh 

#   export API_URL=https://webrag.nss.jkzl.eu 
#   export ADMIN_EMAIL=admin 
#   export ADMIN_PASSWORD=secret 
#   ./04_query.sh "What is Terraform?"

#   MODE=no_rag TOP_K=3 STRICT_GROUNDING=false 
#   ./04_query.sh "Who is rector at MENDELU?"

#   UPSTREAM_PROVIDER=openai UPSTREAM_BASE_URL=https://api.openai.com/v1 
#   UPSTREAM_API_KEY=sk-... UPSTREAM_MODEL=gpt-4o ./04_query.sh "What is Terraform?"

#   UPSTREAM_PROVIDER=openrouter UPSTREAM_BASE_URL=https://openrouter.ai/api/v1 
#   UPSTREAM_API_KEY=sk-or-... UPSTREAM_MODEL=openrouter/auto ./04_query.sh 
#   "In which field specializes FarmAI?"

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
UPSTREAM_PROVIDER="${UPSTREAM_PROVIDER:-}"
UPSTREAM_BASE_URL="${UPSTREAM_BASE_URL:-}"
UPSTREAM_API_KEY="${UPSTREAM_API_KEY:-}"
UPSTREAM_MODEL="${UPSTREAM_MODEL:-}"

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

BODY=$(jq -n \
  --arg question "$QUESTION" \
  --arg mode "$MODE" \
  --argjson top_k "$TOP_K" \
  --argjson strict_grounding "$STRICT_GROUNDING" \
  --arg source_id "$SOURCE_ID" \
  --arg upstream_provider "$UPSTREAM_PROVIDER" \
  --arg upstream_base_url "$UPSTREAM_BASE_URL" \
  --arg upstream_api_key "$UPSTREAM_API_KEY" \
  --arg upstream_model "$UPSTREAM_MODEL" \
  '{
    question: $question,
    mode: $mode,
    top_k: $top_k,
    strict_grounding: $strict_grounding
  }
  + (if $source_id == "" then {} else {source_id: $source_id} end)
  + (if $upstream_provider == "" then {} else {upstream_provider: $upstream_provider} end)
  + (if $upstream_base_url == "" then {} else {upstream_base_url: $upstream_base_url} end)
  + (if $upstream_api_key == "" then {} else {upstream_api_key: $upstream_api_key} end)
  + (if $upstream_model == "" then {} else {upstream_model: $upstream_model} end)')

curl -sf -X POST "${API_URL}/query/" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "$BODY"
echo
