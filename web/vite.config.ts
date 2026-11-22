import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backend = process.env.TADKA_BACKEND ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  // three.js makes one big bundle; fine for a local app.
  build: { chunkSizeWarningLimit: 4000 },
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
    },
  },
})
