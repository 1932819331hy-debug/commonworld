/**
 * Commonworld v1 e2e (Playwright). Run from platform/: `npm run test:e2e` (target: BASE_URL, default local wrangler dev).
 * Projects:
 *   api       request-context specs (no browser): API flows, SEO files, headers, limits. Runs once.
 *   phone     390x844   page specs
 *   tablet    820x1180  page specs
 *   desktop   1440x900  page specs
 * Browser: Playwright's Chromium, or a system Chromium via PW_CHROMIUM_EXECUTABLE (e.g. /usr/bin/chromium on linux-arm64,
 * where Playwright publishes no Chrome build).
 */
import { defineConfig, devices } from '@playwright/test';
import { BASE_URL } from './support/env';

const executablePath = process.env.PW_CHROMIUM_EXECUTABLE || undefined;
const browserUse = { ...devices['Desktop Chrome'], launchOptions: { executablePath } };

export default defineConfig({
  testDir: './specs',
  globalSetup: './global-setup.ts',
  outputDir: './test-results',
  fullyParallel: false,
  workers: 1, // one shared database and per-network registration / rate limits: keep the order predictable
  retries: 0,
  timeout: 60_000,
  reporter: [['list'], ['html', { outputFolder: './playwright-report', open: 'never' }]],
  use: { baseURL: BASE_URL, trace: 'retain-on-failure' },
  projects: [
    { name: 'api', testMatch: /api\/.*\.spec\.ts/ },
    { name: 'phone', testMatch: /pages\/.*\.spec\.ts/, use: { ...browserUse, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 3 } },
    { name: 'tablet', testMatch: /pages\/.*\.spec\.ts/, use: { ...browserUse, viewport: { width: 820, height: 1180 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } },
    { name: 'desktop', testMatch: /pages\/.*\.spec\.ts/, use: { ...browserUse, viewport: { width: 1440, height: 900 } } },
  ],
});
