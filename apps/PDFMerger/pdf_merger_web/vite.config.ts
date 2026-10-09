import vue from '@vitejs/plugin-vue'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

// Host, ports and URLs come from the repo-root .env (shared with pdf_merger);
// real environment variables win over it.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', 'PDF_MERGER_')
  // Everything under /api goes to pdf_merger, so the browser sees one origin:
  // the pm_session cookie works and no CORS is involved. SSE streams through.
  const apiProxy = {
    '/api': { target: env.PDF_MERGER_API_URL || `http://127.0.0.1:${env.PDF_MERGER_PORT || 8040}` },
  }
  return {
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
      port: Number(env.PDF_MERGER_WEB_PORT || 5174),
      strictPort: true,
      // Explicit IPv4: on Windows "localhost" can bind only [::1].
      host: '127.0.0.1',
      proxy: apiProxy,
    },
    preview: { proxy: apiProxy },
  }
})
