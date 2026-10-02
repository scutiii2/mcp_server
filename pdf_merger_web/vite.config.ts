import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// Everything under /api goes to pdf_merger, so the browser sees one origin:
// the pm_session cookie works and no CORS is involved. SSE streams through.
const apiProxy = {
  '/api': { target: process.env.PDF_MERGER_API_URL ?? 'http://127.0.0.1:8040' },
}

export default defineConfig({
  plugins: [vue()],
  // `npm test`: unit tests sit beside their source as *.test.ts.
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
    restoreMocks: true,
    unstubGlobals: true,
  },
  server: {
    // strictPort: fail instead of moving to another port, so server_launcher's port is the real one.
    port: Number(process.env.PDF_MERGER_WEB_PORT ?? 5174),
    strictPort: true,
    // Explicit IPv4: on Windows "localhost" can bind only [::1].
    host: '127.0.0.1',
    proxy: apiProxy,
  },
  preview: { proxy: apiProxy },
})
