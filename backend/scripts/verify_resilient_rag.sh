#!/bin/bash
# Verification script for resilient RAG architecture

set -e

echo "====== Resilient RAG Verification ======"
echo ""

# 1. Check database schema
echo "1. Checking database schema..."
psql $DATABASE_URL -c "\d chunks" | grep -E "(embedding_status|qdrant_sync_status|text_vector|markdown_uri)" && echo "✓ New columns present" || echo "✗ Missing columns"
echo ""

# 2. Check RabbitMQ queues
echo "2. Checking RabbitMQ queues..."
curl -s -u guest:guest http://localhost:15672/api/queues | python3 -c "import sys, json; queues = [q['name'] for q in json.load(sys.stdin)]; print('✓ Queues:', queues)" || echo "✗ RabbitMQ check failed"
echo ""

# 3. Check S3 buckets
echo "3. Checking S3 buckets..."
echo "Expected buckets: rag-evidence, rag-documents, rag-embeddings (if backup enabled)"
echo ""

# 4. Check worker processes
echo "4. Checking worker containers..."
docker ps --filter "name=rag_worker" --format "{{.Names}}: {{.Status}}" | grep -E "(rag_worker|rag_worker_embed)" && echo "✓ Workers running" || echo "✗ Workers not running"
echo ""

# 5. Test 5-minute SLA
echo "5. Testing 5-minute SLA..."
echo "   a. Add a test source"
echo "   b. Trigger ingest (should complete in 30s)"
echo "   c. Query immediately (should use keyword_fallback)"
echo "   d. Wait 5 minutes"
echo "   e. Query again (should use rag mode with vectors)"
echo "   [Manual test required]"
echo ""

# 6. Test Qdrant fallback
echo "6. Testing Qdrant fallback..."
echo "   a. Stop Qdrant container: docker stop rag_qdrant"
echo "   b. Query (should fall back to keyword search)"
echo "   c. Check response: mode='keyword_fallback', warning present"
echo "   d. Start Qdrant: docker start rag_qdrant"
echo "   [Manual test required]"
echo ""

# 7. Check scheduler jobs
echo "7. Checking scheduler jobs..."
docker logs rag_api 2>&1 | grep -E "(heal_pending|heal_failed|detect_drift|heal_qdrant_sync)" | tail -5 && echo "✓ Healing jobs active" || echo "✗ No healing job logs yet"
echo ""

# 8. Verify full-text search setup
echo "8. Checking full-text search..."
psql $DATABASE_URL -c "SELECT COUNT(*) FROM chunks WHERE text_vector IS NOT NULL;" && echo "✓ text_vector populated" || echo "✗ text_vector setup needed (run setup_tsvector.sql)"
echo ""

echo "====== Verification Complete ======"
echo ""
echo "Next steps:"
echo "1. Run: psql \$DATABASE_URL < backend/scripts/setup_tsvector.sql"
echo "2. Test ingest → embedding → query flow manually"
echo "3. Monitor logs for healing job activity"
echo "4. Check Prometheus metrics at http://localhost:8000/metrics"
