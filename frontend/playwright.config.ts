import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  timeout: 45_000,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:38600',
    actionTimeout: 10_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'uv --directory ../backend run --frozen --no-dev python -m tests.e2e_server serve',
      url: 'http://127.0.0.1:38601/api/health',
      reuseExistingServer: false,
      timeout: 120_000,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 38600 --strictPort',
      url: 'http://127.0.0.1:38600',
      reuseExistingServer: false,
      env: { CAPADO_E2E: '1', VITE_DEV_API_TARGET: 'http://127.0.0.1:38601' },
    },
  ],
})
