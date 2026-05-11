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
create_and_ingest "ITHope - Záchrana dat, Obnova dat Brno" "https://www.ithope.cz/zachrana-dat/" "rendered"
create_and_ingest "ITHope - Jak postupovat při záchraně dat" "https://www.ithope.cz/jak-postupovat-pri-zachrane-dat/" "html"
create_and_ingest "ITHope - Mechanické závady pevných disků HDD a jejích možné příčiny" "https://www.ithope.cz/mechanicke-zavady-pevnych-disku-hdd/" "rendered"

create_and_ingest "FarmAI" "https://farmai.eu/" "screenshot"

create_and_ingest "ReCAPTCHA Demo" "https://www.google.com/recaptcha/api2/demo" "html"
create_and_ingest "Overview - Qdrant" "https://qdrant.tech/documentation/overview/" "api"
create_and_ingest "What is Terraform? | Terraform | HashiCorp Developer" "https://developer.hashicorp.com/terraform/intro" "api"
create_and_ingest "Terraform (Software) - Wikipedia" "https://en.wikipedia.org/wiki/Terraform_(software)" "api"
create_and_ingest "What is Terraform? | IBM" "https://www.ibm.com/think/topics/terraform" "api"

create_and_ingest "Blog Python - default posts feed" "http://blog.python.org/feeds/posts/default" "api"
create_and_ingest "xkcd Atom" "https://xkcd.com/atom.xml" "api"
create_and_ingest "Hacker News RSS" "https://hnrss.org/frontpage" "api"

create_and_ingest "Quotes to Scrape" "https://quotes.toscrape.com/" "html"
create_and_ingest "Python Official Blogs" "https://www.python.org/blogs/" "html"
create_and_ingest "Qdrant - Hybrid Queries" "https://qdrant.tech/documentation/search/hybrid-queries/" "html"

create_and_ingest "Quotes to Scrape - JS" "https://https://quotes.toscrape.com/js/" "rendered"
create_and_ingest "Quotes to Scrape - Scroll" "https://https://quotes.toscrape.com/scroll" "rendered"

create_and_ingest "xkcd" "https://xkcd.com/" "screenshot"
create_and_ingest "quotes.toscrape" "https://quotes.toscrape.com/tableful/" "screenshot"

create_and_ingest "AWS - What is RAG?" "https://aws.amazon.com/what-is/retrieval-augmented-generation/" "api"
create_and_ingest "Nvidia Blog - What is RAG" "https://blogs.nvidia.com/blog/what-is-retrieval-augmented-generation/" "api"
create_and_ingest "Retrieval-augmented Generation | Wiki" "https://en.wikipedia.org/wiki/Retrieval-augmented_generation" "html"

create_and_ingest "Embeddings - HF MTEB (Embedding) Leaderboard" "https://huggingface.co/spaces/mteb/leaderboard" "api"
create_and_ingest "Embeddings - Hugging Face BGE-M3" "https://huggingface.co/BAAI/bge-m3" "api"
create_and_ingest "Embeddings - BGE Model; BGE-M3" "https://bge-model.com/bge/bge_m3.html" "api"
create_and_ingest "Embeddings - M3-Embedding" "https://arxiv.org/abs/2402.03216" "api"

create_and_ingest "Hybrid Search" "https://qdrant.tech/documentation/search/hybrid-queries/" "api"
create_and_ingest "Hybrid Search" "https://qdrant.tech/course/essentials/day-3/hybrid-search/" "api"
create_and_ingest "Hybrid Search" "https://qdrant.tech/documentation/tutorials-search-engineering/reranking-hybrid-search/" "api"

create_and_ingest "Vector Databases - Qdrant docs." "https://qdrant.tech/documentation/" "api"
create_and_ingest "Vector Databases - Qdrant docs; Collections" "https://qdrant.tech/documentation/concepts/collections/" "api"
create_and_ingest "Vector Databases - Qdrant docs; Points" "https://qdrant.tech/documentation/concepts/points/" "api"
create_and_ingest "Vector Databases - Qdrant docs; Vectors" "https://qdrant.tech/documentation/concepts/vectors/" "api"

create_and_ingest "Fake link" "https://f.a.k.e" "api"

create_and_ingest "MENDELU - Main Website" "https://mendelu.cz/" "api"
create_and_ingest "MENDELU - About University" "https://mendelu.cz/o-univerzite/" "api"
create_and_ingest "MENDELU - News" "https://mendelu.cz/aktuality/" "api"

create_and_ingest "PEF MENDELU - Main Website" "https://pef.mendelu.cz/" "api"
create_and_ingest "PEF MENDELU - Basic Information" "https://pef.mendelu.cz/o-fakulte/zakladni-informace/" "api"
create_and_ingest "PEF MENDELU - Organizational Structure" "https://pef.mendelu.cz/o-fakulte/organizacni-struktura/" "api"

create_and_ingest "LDF MENDELU - Main Website" "https://ldf.mendelu.cz/" "api"
create_and_ingest "LDF MENDELU - News" "https://ldf.mendelu.cz/aktuality/" "api"

echo ""
echo "Done. Monitor progress at ${API_URL}/sources/ or in the Pipeline view."


# What is an embedding model?
# What does BGE-M3 do?
# Why is BGE-M3 useful for multilingual search?
# What does multi-functionality mean in BGE-M3?
# What does multi-granularity mean?
# How is BGE-M3 different from a normal keyword search?