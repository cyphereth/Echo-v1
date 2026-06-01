import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/brands':    { target: 'http://localhost:8000', changeOrigin: true },
      '/inbox':     { target: 'http://localhost:8000', changeOrigin: true },
      '/mentions':  { target: 'http://localhost:8000', changeOrigin: true },
      '/onboarding':{ target: 'http://localhost:8000', changeOrigin: true },
      '/search':    { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
