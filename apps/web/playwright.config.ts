import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/smoke",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "node tests/smoke/backend-stub.mjs",
      url: "http://127.0.0.1:4100/health",
      reuseExistingServer: false,
      env: { SMOKE_BACKEND_TOKEN: "smoke-backend-token", PORT: "4100" },
    },
    {
      command: "corepack pnpm dev --hostname 127.0.0.1 --port 3100",
      url: "http://127.0.0.1:3100",
      reuseExistingServer: false,
      env: {
        VERBAOPS_API_BASE_URL: "http://127.0.0.1:4100",
        VERBAOPS_API_TOKEN: "smoke-backend-token",
        PORT: "3100",
      },
    },
  ],
});
