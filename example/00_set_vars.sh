#!/usr/bin/env bash
# Prompt for shared API variables, then run one example API script.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

prompt_default() {
  local var_name="$1"
  local prompt="$2"
  local default_value="$3"
  local value

  read -rp "${prompt} [${default_value}]: " value
  printf -v "$var_name" '%s' "${value:-$default_value}"
}

prompt_default API_URL "API_URL" "${API_URL:-http://localhost:8000}"
prompt_default ADMIN_EMAIL "ADMIN_EMAIL" "${ADMIN_EMAIL:-admin@example.com}"

if [[ -z "${ADMIN_PASSWORD:-}" ]]; then
  read -rsp "ADMIN_PASSWORD: " ADMIN_PASSWORD
  echo
else
  read -rsp "ADMIN_PASSWORD [already set, press Enter to keep]: " password_override
  echo
  ADMIN_PASSWORD="${password_override:-$ADMIN_PASSWORD}"
fi

export API_URL ADMIN_EMAIL ADMIN_PASSWORD

echo
echo "Select script to run:"
echo "1) 01_add_sources.sh"
echo "2) 02_check_knowledge_base.sh"
echo "3) 03_list_sources.sh"
echo "4) 04_query.sh"
read -rp "Choice [1-4]: " choice

case "$choice" in
  1)
    exec "${SCRIPT_DIR}/01_add_sources.sh"
    ;;
  2)
    exec "${SCRIPT_DIR}/02_check_knowledge_base.sh"
    ;;
  3)
    exec "${SCRIPT_DIR}/03_list_sources.sh"
    ;;
  4)
    read -rp "Question: " question
    if [[ -z "$question" ]]; then
      echo "ERROR: question cannot be empty" >&2
      exit 1
    fi
    exec "${SCRIPT_DIR}/04_query.sh" "$question"
    ;;
  *)
    echo "ERROR: invalid choice" >&2
    exit 1
    ;;
esac
