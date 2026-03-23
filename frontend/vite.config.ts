import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/auth': 'http://localhost:8000',
      '/sources': 'http://localhost:8000',
      '/query': 'http://localhost:8000',
      '/incidents': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
