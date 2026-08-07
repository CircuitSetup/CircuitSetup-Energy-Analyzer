import { defineConfig, devices } from "@playwright/test";

const haBaseUrl = process.env.HA_BASE_URL;

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: !haBaseUrl,
  workers: haBaseUrl ? 1 : undefined,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", {
    outputFolder: haBaseUrl ? "playwright-report/ha" : "playwright-report/static",
    open: "never",
  }]],
  outputDir: haBaseUrl ? "test-results/browser/ha" : "test-results/browser/static",
  use: {
    baseURL: haBaseUrl || "http://127.0.0.1:4173",
    timezoneId: "UTC",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
    serviceWorkers: "block",
  },
  projects: haBaseUrl ? [
    {
      name: "Home Assistant Chromium",
      testMatch: "ha-panel.spec.js",
      use: devices["Desktop Chrome"],
    },
  ] : [
    {
      name: "Desktop Chromium",
      testIgnore: "ha-panel.spec.js",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1000 },
      },
    },
    {
      name: "Mobile Chromium",
      testIgnore: "ha-panel.spec.js",
      use: {
        ...devices["Pixel 7"],
        browserName: "chromium",
        viewport: { width: 390, height: 844 },
      },
    },
  ],
  webServer: haBaseUrl ? undefined : {
    command: "python -m http.server 4173 --bind 127.0.0.1",
    url: "http://127.0.0.1:4173/tests/e2e/panel.html",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
