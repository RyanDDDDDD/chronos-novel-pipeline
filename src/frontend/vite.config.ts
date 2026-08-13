import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const rootDir = path.dirname(fileURLToPath(import.meta.url))

// run.py resolves the backend's actual port at startup (auto-incrementing past
// conflicts, see _find_free_port in src/backend/main.py) and exports it here so
// this proxy doesn't assume a fixed 8775. Falls back to 8775 for standalone
// `vite dev` runs outside run.py.
const backendPort = process.env.CHRONOS_BACKEND_PORT || '8775'

// Without an explicit keep-alive agent, http-proxy (the library backing Vite's
// server.proxy) opens a brand-new short-lived TCP connection to the backend for
// every single proxied /api request and tears it down right after -- on Windows
// this frequently races the backend's own Proactor socket cleanup and surfaces as
// spurious "[asyncio] connection reset during transport cleanup" WinError 10054
// noise (and needlessly burns through the ephemeral port range under heavy REST
// traffic). Reusing one keep-alive agent across requests avoids both.
const apiProxyAgent = new http.Agent({ keepAlive: true })

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(rootDir, 'src'),
    },
  },
  server: {
    // Pin to IPv4 loopback: on some Windows setups "localhost" resolves to the
    // IPv6 loopback first, so Vite would bind [::1] only. dev_console.py's
    // dashboard health probe (and main.py's port-in-use check) connect to
    // 127.0.0.1 specifically, so an IPv6-only bind leaves the dashboard's
    // "vite" row stuck at "starting" forever even though Vite is actually up.
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/ws': {
        target: `ws://localhost:${backendPort}`,
        ws: true,
        rewrite: (path) => path,
      },
      '/api': {
        target: `http://localhost:${backendPort}`,
        changeOrigin: true,
        agent: apiProxyAgent,
      },
    },
  },
})
