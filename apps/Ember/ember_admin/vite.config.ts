import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'
import { defineConfig } from 'vitest/config'

// ember_admin: everything under /api goes to ember_api, so the browser sees one origin:
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
  plugins: [vue(), VitePWA({
    registerType: 'prompt',
    injectRegister: null,
    includeAssets: ['favicon.svg', 'icons/*.png'],
    manifest: {
      id: '/',
      name: 'Ember Admin',
      short_name: 'Ember Admin',
      description: 'Manage your Ember workspace.',
      start_url: '/admin',
      scope: '/',
      display: 'standalone',
      background_color: '#17171a',
      theme_color: '#e8590c',
      icons: [
        { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
        { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
        { src: '/icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
      ],
    },
    workbox: {
      // Cache only versioned UI files. Account data, API calls, and downloads stay on the network.
      globPatterns: ['**/*.{js,css,html}'],
      navigateFallback: '/index.html',
      navigateFallbackDenylist: [/^\/api(?:\/|$)/],
      runtimeCaching: [],
      cleanupOutdatedCaches: true,
    },
  })],
  build: {
    // style.css colors are light-dark() tokens (the theme toggle sets
    // color-scheme). Below these versions the CSS minifier rewrites them into
    // a prefers-color-scheme query, which the toggle can't override.
    cssTarget: ['chrome123', 'firefox120', 'safari17.5'],
  },
  // `npm test`: unit tests sit beside their source as *.test.ts. jsdom gives
  // the stores and components a browser-like document and localStorage.
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
    restoreMocks: true,
  },
  server: {
    // Set by run.bat / server_launcher. strictPort: fail instead of silently
    // moving to the next port, so the launcher's port is always the real one.
    port: Number(process.env.EMBER_ADMIN_PORT ?? 5176),
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
