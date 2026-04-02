<script setup lang="ts">
import { ref } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import Card from 'primevue/card';
import { useCounterStore } from '@/stores/counter';

// Remove later these are examples
import ItemsCard from '@/views/ExampleItems.vue'
import RagCard from '@/views/ExampleRag.vue'

const counter = useCounterStore();
const text = ref('');
</script>

<template>
  <main class="flex flex-col items-center justify-center py-12">
    <div class="max-w-2xl w-full">
      <Card>
        <template #title>
          <h1 class="text-3xl font-bold text-center">Modern Vue 3 + PrimeVue</h1>
        </template>
        <template #content>
          <div class="flex flex-col gap-6">
            <section class="flex flex-col gap-2">
              <label for="username" class="font-semibold">Test InputText</label>
              <InputText id="username" v-model="text" placeholder="Type something..." />
              <p v-if="text" class="text-sm text-surface-500">You typed: {{ text }}</p>
            </section>

            <section class="flex flex-col gap-2 p-4 bg-surface-50 dark:bg-surface-800 rounded-lg">
              <h3 class="font-bold">Pinia State Management</h3>
              <p>Count: {{ counter.count }} (Double: {{ counter.doubleCount }})</p>
              <Button label="Increment" @click="counter.increment" class="w-fit" />
            </section>

            <div class="flex justify-center mt-4">
              <Button label="Success" severity="success" icon="pi pi-check" />
            </div>
          </div>
        </template>
      </Card>

      <!-- Connected API example remvove later-->
      <ItemsCard/>
      <RagCard />
    </div>
  </main>
</template>
