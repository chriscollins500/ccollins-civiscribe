import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 90_000,
  expect: {
    timeout: 15_000,
  },
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: process.env.CIVISCRIBE_E2E_BASE_URL ?? "http://127.0.0.1:8191",
    channel: process.env.CIVISCRIBE_E2E_CHANNEL ?? "msedge",
    headless: true,
    viewport: {
      width: 1440,
      height: 1000,
    },
    trace: "retain-on-failure",
  },
});
