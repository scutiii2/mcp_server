import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Everything under /api goes to ember_api, so the browser sees one origin:
// the session cookie just works and no CORS is involved. ember_api then
// proxies MCP on to ai_agent / mcp_server.
// xfwd: adds X-Forwarded-For, so ember_api (which trusts it only from
// loopback) rate-limits logins per real client, not per proxy.
const apiProxy = {
  '/api': { target: `http://127.0.0.1:${process.env.EMBER_API_PORT ?? 8030}`, xfwd: true },
}

// For the built app (`vite preview`). Not on the dev server: HMR needs
// inline scripts and its own websocket. 'unsafe-inline' styles only: Vue
// sets style attributes at runtime.
const contentSecurityPolicy = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join('; ')

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    // Set by run.bat / server_launcher. strictPort: fail instead of silently
    // moving to the next port, so the launcher's port is always the real one.
    port: Number(process.env.EMBER_WEB_PORT ?? 5173),
    strictPort: true,
    // Explicit IPv4: on Windows "localhost" can bind only [::1], which the
    // launcher's 127.0.0.1 port check would miss.
    host: '127.0.0.1',
    proxy: apiProxy,
  },
  // `vite preview` (the production build) talks to ember_api the same way.
  preview: {
    proxy: apiProxy,
    headers: {
      'Content-Security-Policy': contentSecurityPolicy,
      'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY',
      'Referrer-Policy': 'no-referrer',
    },
  },
})
