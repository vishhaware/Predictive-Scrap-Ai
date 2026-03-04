import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const backendTarget = process.env.VITE_BACKEND_URL || env.VITE_BACKEND_URL || 'http://127.0.0.1:8000'
  const backendWsTarget = process.env.VITE_BACKEND_WS_URL || env.VITE_BACKEND_WS_URL || backendTarget.replace(/^http/i, 'ws')
  const enableWsProxy = String(process.env.VITE_ENABLE_WS_PROXY || env.VITE_ENABLE_WS_PROXY || '').toLowerCase() === 'true'

  const proxy = {
    '/api': {
      target: backendTarget,
      changeOrigin: true,
    },
  }

  if (enableWsProxy) {
    proxy['/ws'] = {
      target: backendWsTarget,
      changeOrigin: true,
      ws: true,
    }
  }

  return {
    plugins: [react()],
    server: {
      proxy,
    },
  }
})
