import { defineConfig } from "@playwright/test";

// A spare port, so the test never meets a dev server of yours on 5176/4173.
const PORT = Number(process.env.EMBER_E2E_PORT ?? 5198);

// `npm run test:e2e`. The browser is the Chrome installed on this machine (no
// download); ember_api is not needed because the test answers every /api call itself.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel: "chrome",
    trace: "retain-on-failure",
  },
  webServer: {
    // The built app, served the way production serves it (with its security headers).
    command: `npx vite build && npx vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
