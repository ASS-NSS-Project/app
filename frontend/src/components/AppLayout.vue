<template>
  <!--
    Two-column shell layout: sidebar on the left, page content on the right.
    AppSidebar is always rendered. The actual page content is provided via
    the default slot — every view wraps itself in <AppLayout> to get the sidebar.
    flex: 1 on .main-content means it takes all remaining horizontal space
    after the 160px sidebar. min-width: 0 prevents flex children from
    overflowing their container when content is wider than the available space.
  -->
  <div class="app-shell">
    <AppSidebar />
    <main class="main-content">
      <slot />
    </main>
  </div>
</template>

<script setup lang="ts">
/**
 * AppLayout.vue — Two-column page shell (sidebar + content area)
 *
 * Wraps every authenticated view. Usage:
 *   <AppLayout>
 *     <div class="page">...</div>
 *   </AppLayout>
 *
 * The content slot is rendered inside the scrollable main area.
 * The sidebar is always visible and contains navigation + user info.
 */
import AppSidebar from './AppSidebar.vue'
</script>

<style scoped>
/* Full-height flex container: sidebar + main side by side */
.app-shell {
  display: flex;
  min-height: 100vh;
}

/* Main content area — fills remaining width, scrolls independently */
.main-content {
  flex: 1;
  min-width: 0;       /* allow content to shrink below its natural size in flex context */
  overflow-y: auto;
}
</style>
