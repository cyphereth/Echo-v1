import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/brands':     'http://127.0.0.1:8000',
      '/inbox':      'http://127.0.0.1:8000',
      '/mentions':   'http://127.0.0.1:8000',
      '/onboarding': 'http://127.0.0.1:8000',
      '/search':     'http://127.0.0.1:8000',
      '/health':     'http://127.0.0.1:8000',
    },
  },
})
