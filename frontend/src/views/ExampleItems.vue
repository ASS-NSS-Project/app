<script setup lang="ts">
import { ref, onMounted } from 'vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Card from 'primevue/card'

// --- state ---
const name = ref('')
const description = ref('')
const items = ref([])

// --- API calls ---
async function loadItems() {
  const res = await fetch('/api/items/')
  items.value = await res.json()
}

async function createItem() {
  await fetch('/api/items/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      name: name.value,
      description: description.value,
    }),
  })

  // refresh list after creation
  await loadItems()

  // clear inputs (optional)
  name.value = ''
  description.value = ''
}

// load items on mount
onMounted(loadItems)
</script>

<template>
  <Card class="mt-6">
    <template #title>
      <h2 class="text-xl font-bold">Items Demo</h2>
    </template>

    <template #content>
      <div class="flex flex-col gap-4">

        <!-- Create item -->
        <div class="flex flex-col gap-2">
          <InputText v-model="name" placeholder="Name..." />
          <InputText v-model="description" placeholder="Description..." />
          <Button label="Create Item" @click="createItem" class="w-fit" />
        </div>

        <!-- Items list -->
        <div class="flex flex-col gap-2">
          <h3 class="font-semibold">Items:</h3>

          <ul v-if="items.length">
            <li v-for="item in items" :key="item.id">
              {{ item.name }} - {{ item.description }}
            </li>
          </ul>

          <p v-else class="text-sm text-surface-500">
            No items yet.
          </p>
        </div>

      </div>
    </template>
  </Card>
</template>