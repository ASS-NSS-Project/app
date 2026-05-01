<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Experiments</h2>
        <p>Evaluate RAG retrieval quality</p>
      </div>
      <div class="placeholder-box">
        <span class="placeholder-text">To be done...</span>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
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
