import { expect, test, type Page } from '@playwright/test';

async function register(page: Page) {
  const email = `e2e-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`;
  await page.goto('/');
  const accountButton = page.getByRole('button', { name: '本地账户' });
  if (await accountButton.isVisible()) {
    await accountButton.click();
  } else {
    await page.locator('.mobile-nav').getByRole('button', { name: '我的', exact: true }).click();
    await page.getByRole('button', { name: '登录 / 注册' }).click();
  }
  await page.getByRole('button', { name: '没有账户？立即注册' }).click();
  await page.getByLabel('昵称').fill('端到端测试用户');
  await page.getByLabel('邮箱').fill(email);
  await page.getByLabel('密码').fill('E2e-password-2026');
  await page.getByRole('button', { name: '注册', exact: true }).click();
  await expect(page.getByText('账户创建成功，请查收验证邮件。')).toBeVisible();
  if (await page.getByRole('button', { name: '端到端测试用户' }).isVisible()) return;
  await expect(page.getByRole('heading', { name: '端到端测试用户' })).toBeVisible();
}

test.describe('consumer account navigation', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name.includes('mobile'), 'desktop account navigation suite');
    await register(page);
  });

  test('account KPI cards and explicit back actions open usable pages', async ({ page }) => {
    await page.getByRole('button', { name: '我的', exact: true }).first().click();

    const journeys = [
      ['累计记录节省', '省钱中心'],
      ['决策报告', '报告与清单'],
      ['收藏商品', '收藏与足迹'],
      ['购买记录', '订单与售后'],
    ] as const;

    for (const [card, heading] of journeys) {
      await page.getByRole('button', { name: new RegExp(`打开.*${card}`) }).click();
      await expect(page.getByRole('heading', { name: heading })).toBeVisible();
      await page.getByRole('button', { name: '返回我的' }).click();
      await expect(page.getByRole('heading', { name: '端到端测试用户' })).toBeVisible();
    }
  });

  test('primary routes remain usable after refresh and browser history', async ({ page }) => {
    await page.getByRole('button', { name: '收藏足迹', exact: true }).click();
    await expect(page.getByRole('heading', { name: '收藏与足迹' })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: '收藏与足迹' })).toBeVisible();

    await page.getByRole('button', { name: '发现', exact: true }).click();
    await expect(page.getByText('最近看过')).toBeVisible();
    await expect(page.locator('[role="alert"]')).toHaveCount(0);
  });
});

test('mobile bottom navigation exposes all core consumer journeys', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes('mobile'), 'mobile-only navigation assertion');
  await register(page);
  const nav = page.locator('.mobile-nav');
  await expect(nav).toBeVisible();
  for (const [button, heading] of [
    ['省钱', '省钱中心'],
    ['消息', '消息'],
    ['我的', '端到端测试用户'],
  ] as const) {
    await nav.getByRole('button', { name: button, exact: true }).click();
    await expect(page.getByRole('heading', { name: heading })).toBeVisible();
  }
});
