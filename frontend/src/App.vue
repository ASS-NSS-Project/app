<script setup lang="ts">
import { RouterView } from 'vue-router'
</script>

<template>
  <header class="p-4 bg-surface-50 dark:bg-surface-900 border-b border-surface-200 dark:border-surface-700 mb-8">
    <nav class="container mx-auto">
      <h2 class="text-xl font-semibold">My PrimeVue App</h2>
    </nav>
  </header>

  <div class="container mx-auto px-4">
    <RouterView />
  </div>
</template>

<style>
body {
  margin: 0;
  font-family: var(--p-font-family, system-ui, -apple-system, sans-serif);
  background-color: var(--p-surface-0);
  color: var(--p-surface-900);
}
</style>
