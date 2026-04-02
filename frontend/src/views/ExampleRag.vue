<script setup lang="ts">
import { ref } from 'vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Card from 'primevue/card'

const ragText = ref('')
const ragQuery = ref('')
const ragAnswer = ref('')
const ragStatus = ref('')

async function addText() {
  const res = await fetch('/api/rag/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: ragText.value }),
  })

  const data = await res.json()
  ragStatus.value = data.status
}

async function askRag() {
  const res = await fetch('/api/rag/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: ragQuery.value }),
  })

  const data = await res.json()
  ragAnswer.value = data.answer
}
</script>

<template>
  <Card class="mt-6">
    <template #title>
      <h2 class="text-xl font-bold">RAG Demo</h2>
    </template>

    <template #content>
      <div class="flex flex-col gap-4">

        <div class="flex flex-col gap-2">
          <InputText v-model="ragText" placeholder="Text to store..." />
          <Button label="Add Text" @click="addText" class="w-fit" />
          <p v-if="ragStatus" class="text-sm">Status: {{ ragStatus }}</p>
        </div>

        <div class="flex flex-col gap-2">
          <InputText v-model="ragQuery" placeholder="Ask something..." />
          <Button label="Ask" @click="askRag" class="w-fit" />
          <p v-if="ragAnswer" class="text-sm">Answer: {{ ragAnswer }}</p>
        </div>

      </div>
    </template>
  </Card>
</template>