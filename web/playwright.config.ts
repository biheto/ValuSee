import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI ? [['html', { open: 'never' }], ['github']] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:5174',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile-chromium', use: { ...devices['Pixel 7'] } },
  ],
  webServer: [
    {
      command: `"${process.env.PYTHON_BIN || 'python'}" -m uvicorn app.main:app --host 127.0.0.1 --port 8101`,
      cwd: '..',
      url: 'http://127.0.0.1:8101/health',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ...process.env,
        APP_ENV: 'test',
        VALUSee_JWT_SECRET: 'e2e-only-secret-not-for-production-use',
        VALUSee_SQLITE_PATH: '.test-tmp/e2e-valuesee.db',
        VALUSee_EMAIL_TRANSPORT: 'console',
      },
    },
    {
      command: 'npm run dev -- --port 5174',
      cwd: '.',
      url: 'http://127.0.0.1:5174',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { ...process.env, VALUSee_API_TARGET: 'http://127.0.0.1:8101' },
    },
  ],
});
