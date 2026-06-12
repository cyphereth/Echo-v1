import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/brands':     'http://127.0.0.1:8000',
      '/inbox':      'http://127.0.0.1:8000',
      '/mentions':   'http://127.0.0.1:8000',
      '/comments':   'http://127.0.0.1:8000',
      '/onboarding': 'http://127.0.0.1:8000',
      '/search':     'http://127.0.0.1:8000',
      '/analytics':  'http://127.0.0.1:8000',
      '/auth':       'http://127.0.0.1:8000',
      '/health':       'http://127.0.0.1:8000',
      '/explore':      'http://127.0.0.1:8000',
      '/opportunities':'http://127.0.0.1:8000',
      '/debug':        'http://127.0.0.1:8000',
    },
  },
})
