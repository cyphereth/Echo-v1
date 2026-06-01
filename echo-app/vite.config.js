import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/brands':    'http://localhost:8000',
      '/inbox':     'http://localhost:8000',
      '/mentions':  'http://localhost:8000',
      '/onboarding':'http://localhost:8000',
      '/search':    'http://localhost:8000',
      '/health':    'http://localhost:8000',
    },
  },
})
