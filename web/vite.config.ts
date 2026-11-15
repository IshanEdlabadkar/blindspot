import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev, the API (uvicorn api.app:app --port 8600) answers /api; in the demo it serves web/dist itself.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': { target: 'http://127.0.0.1:8600', changeOrigin: true } } },
})
