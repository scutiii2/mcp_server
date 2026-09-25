import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

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
  },
})
