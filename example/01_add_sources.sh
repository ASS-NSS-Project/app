#!/usr/bin/env bash
# Seed the example sources and trigger an initial ingest for each.
# Usage:
#   ./01_add_sources.sh 

#   export API_URL=https://webrag.nss.jkzl.eu
#   export ADMIN_EMAIL=admin 
#   export ADMIN_PASSWORD=secret 
#   ./01_add_sources.sh

set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"

if [[ -z "$ADMIN_PASSWORD" ]]; then
  read -rsp "Admin password: " ADMIN_PASSWORD
  echo
fi

# ── 1. Login ──────────────────────────────────────────────────────────────────

echo "Logging in as ${ADMIN_EMAIL}..."
TOKEN=$(curl -sf -X POST "${API_URL}/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=${ADMIN_EMAIL}&password=${ADMIN_PASSWORD}" \
  | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: login failed — check API_URL, ADMIN_EMAIL, ADMIN_PASSWORD" >&2
  exit 1
fi
echo "OK (token acquired)"

AUTH=(-H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json")

# ── 2. Helper: create source + trigger ingest ─────────────────────────────────

create_and_ingest() {
  local name="$1"
  local url="$2"
  local strategy="$3"

  echo ""
  echo "Creating source: ${name} (${strategy}) → ${url}"
  SOURCE_ID=$(curl -sf -X POST "${API_URL}/sources/" \
    "${AUTH[@]}" \
    -d "{\"name\":\"${name}\",\"base_url\":\"${url}\",\"preferred_strategy\":\"${strategy}\",\"crawl_frequency_hours\":24}" \
    | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)

  if [[ -z "$SOURCE_ID" ]]; then
    echo "  WARN: source may already exist or creation failed — skipping ingest"
    return
  fi
  echo "  Created → ${SOURCE_ID}"

  echo "  Triggering ingest..."
  JOB_ID=$(curl -sf -X POST "${API_URL}/sources/${SOURCE_ID}/ingest" \
    "${AUTH[@]}" \
    -d '{}' \
    | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
  echo "  Ingest job queued → ${JOB_ID}"
}

# ── 3. Seed sources ───────────────────────────────────────────────────────────

create_and_ingest "MENDELU" "https://mendelu.cz" "html"
create_and_ingest "ITHope" "https://www.ithope.cz/" "rendered"
create_and_ingest "FarmAI" "https://farmai.eu/" "screenshot"
create_and_ingest "ReCAPTCHA Demo" "https://www.google.com/recaptcha/api2/demo" "html"
create_and_ingest "ReCAPTCHA Demo" "https://www.google.com/recaptcha/api2/demo" "api"
create_and_ingest "Overview - Qdrant" "https://qdrant.tech/documentation/overview/" "api"
create_and_ingest "What is Terraform? | Terraform | HashiCorp Developer" "https://developer.hashicorp.com/terraform/intro" "api"
create_and_ingest "Terraform (Software) - Wikipedia" "https://en.wikipedia.org/wiki/Terraform_(software)" "api"
create_and_ingest "What is Terraform? | IBM" "https://www.ibm.com/think/topics/terraform" "api"

echo ""
echo "Done. Monitor progress at ${API_URL}/sources/ or in the Pipeline view."
