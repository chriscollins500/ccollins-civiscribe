import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const publishedURL = process.env.CIVISCRIBE_SITE_BASE_URL;
const python =
  process.platform === "win32"
    ? path.join(root, ".venv/Scripts/python.exe")
    : "python";
export default defineConfig({
  testDir: ".",
  testMatch: "browser.spec.mjs",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [
    ["line"],
    [
      "json",
      { outputFile: path.join(root, ".tmp/site-qa/browser-results.json") },
    ],
  ],
  outputDir: path.join(root, ".tmp/site-test-results"),
  use: {
    baseURL: publishedURL || "http://127.0.0.1:8793/ccollins-civiscribe/",
    channel: process.env.CI ? undefined : "msedge",
    launchOptions: { chromiumSandbox: true },
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 1000 } } },
    {
      name: "mobile",
      use: { ...devices["iPhone 13"], defaultBrowserType: "chromium" },
    },
  ],
  webServer: publishedURL
    ? undefined
    : {
        command: `"${python}" -m http.server 8793 --bind 127.0.0.1 --directory ".tmp/site-preview"`,
        cwd: root,
        url: "http://127.0.0.1:8793/ccollins-civiscribe/",
        reuseExistingServer: false,
        timeout: 30_000,
      },
});
