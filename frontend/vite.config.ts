import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  envDir: false,
  envPrefix: [],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/v1': { target: 'http://127.0.0.1:8000', proxyTimeout: 300_000, timeout: 300_000 },
      '/health': { target: 'http://127.0.0.1:8000' },
    },
  },
  build: { sourcemap: false },
})
