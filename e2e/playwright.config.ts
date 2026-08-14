import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests against a running stack.
 *
 * No `webServer` block: the stack is Docker, brought up by
 * `docker compose up -d`, and having Playwright try to own its lifecycle would
 * mean a second definition of how to start this product. The runner checks the
 * stack is up and says so if it isn't.
 *
 * `baseURL` is the same single origin everything else uses. That matters here
 * more than usual — the session cookie is first-party precisely because the
 * SPA and the API share a host, so testing through anything else would be
 * testing a configuration nobody runs.
 */
export default defineConfig({
  testDir: "./tests",
  // These drive one shared stack with real accounts. Parallel workers would be
  // fine (every test makes its own account) but a failure is much easier to
  // read when the log is in order.
  workers: 1,
  fullyParallel: false,
  // Fail the run if someone leaves a .only in.
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  outputDir: "./artifacts",
  use: {
    baseURL: process.env.SITE_URL ?? "http://localhost",
    // Kept only for failures — a passing run shouldn't leave hundreds of
    // megabytes of video behind.
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
