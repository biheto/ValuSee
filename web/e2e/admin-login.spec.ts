import { expect, test } from '@playwright/test';

test('admin login submits the captcha and renders API errors as readable text', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('valuesee-token', 'expired-token'));
  const captchaResponsePromise = page.waitForResponse((response) => response.url().includes('/api/v1/auth/captcha'));

  await page.goto('/admin');
  const captcha = await (await captchaResponsePromise).json() as { code: string };

  await page.getByLabel('管理员邮箱').fill('missing-admin@example.com');
  await page.getByLabel('密码', { exact: true }).fill('invalid-password');
  await page.getByLabel('图形验证码输入').fill(captcha.code);

  const loginResponsePromise = page.waitForResponse((response) => response.url().includes('/api/v1/auth/login'));
  await page.locator('.admin-primary').click();
  const loginResponse = await loginResponsePromise;

  expect(loginResponse.status()).toBe(401);
  await expect(page.locator('.admin-error')).toContainText('邮箱或密码错误');
  await expect(page.locator('.admin-error')).not.toContainText('[object Object]');
  await expect(page.locator('.character-captcha img')).toBeVisible();
});
