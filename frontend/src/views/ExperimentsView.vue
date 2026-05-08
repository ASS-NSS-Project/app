<template>
  <!--
    ExperimentsView — Batch RAG benchmark experiments (not yet implemented).
    This view is registered in the router and accessible to admin and analyst
    roles, but the feature is pending implementation. The placeholder text
    prevents a blank page from appearing in the sidebar.
  -->
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Experiments</h2>
        <p>Evaluate RAG retrieval quality</p>
      </div>
      <!-- Placeholder until the feature is implemented (see services/experiment.py) -->
      <div class="placeholder-box">
        <span class="placeholder-text">To be done...</span>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
/**
 * ExperimentsView.vue — Placeholder for batch RAG evaluation experiments
 *
 * When implemented, this view will allow admins and analysts to:
 * - Create named experiment sets with queries and expected keywords.
 * - Run experiments against the live RAG pipeline.
 * - View per-query metrics (Recall@k, MRR, nDCG, latency) and aggregate scores.
 *
 * Backend stub: routers/experiments.py and services/experiment.py.
 */
import AppLayout from '@/components/AppLayout.vue'
</script>

<style scoped>
.page {
  padding: 2rem;
}

.page-header {
  margin-bottom: 2rem;
}

.page-header h2 {
  font-size: 1.5rem;
  font-weight: 600;
  margin: 0 0 0.25rem;
}

.page-header p {
  color: var(--color-text-muted, #6b7280);
  margin: 0;
}

.placeholder-box {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 12rem;
  color: var(--color-text-muted, #6b7280);
}

.placeholder-text {
  font-size: 1.1rem;
}
</style>
