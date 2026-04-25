<template>
  <div class="app-shell">
    <AppSidebar />
    <main class="main-content">
      <slot />
    </main>
  </div>
</template>

<script setup lang="ts">
import AppSidebar from './AppSidebar.vue'
</script>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
}
.main-content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
}
</style>
