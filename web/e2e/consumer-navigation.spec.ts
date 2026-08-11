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
  await page.getByLabel('邮箱', { exact: true }).fill(email);
  await page.getByRole('button', { name: '获取验证码' }).click();
  await expect(page.getByLabel('邮箱验证码')).toHaveValue(/^\d{6}$/);
  await page.getByLabel('密码', { exact: true }).fill('E2e-password-2026');
  await page.getByLabel('确认密码').fill('E2e-password-2026');
  await page.getByRole('button', { name: '注册', exact: true }).click();
  await expect(page.getByText('邮箱验证完成，账户创建成功。')).toBeVisible();
  if (!(await page.getByRole('button', { name: '端到端测试用户' }).isVisible())) {
    await expect(page.getByRole('heading', { name: '端到端测试用户' })).toBeVisible();
  }
  return email;
}

test('password reset email opens a validated double-entry reset flow', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes('mobile'), 'covered once on desktop');
  const email = await register(page);

  await page.getByRole('button', { name: '端到端测试用户' }).click();
  await page.getByRole('button', { name: '退出登录' }).click();
  await page.getByRole('button', { name: '本地账户' }).click();
  await page.getByRole('button', { name: '忘记密码' }).click();
  await page.getByLabel('邮箱', { exact: true }).fill(email);
  const responsePromise = page.waitForResponse((response) => response.url().includes('/auth/password/reset/request'));
  await page.getByRole('button', { name: '发送重置邮件' }).click();
  const response = await responsePromise;
  expect(response.ok()).toBeTruthy();
  const { reset_token: resetToken } = await response.json();
  expect(resetToken).toBeTruthy();
  await expect(page.getByText(/重置邮件将很快送达/)).toBeVisible();

  await page.goto(`/?reset_token=${encodeURIComponent(resetToken)}`);
  await expect(page.getByRole('heading', { name: '设置新密码' })).toBeVisible();
  await page.locator('.account-backdrop').click({ position: { x: 5, y: 5 } });
  await page.getByRole('button', { name: '本地账户' }).click();
  await expect(page.getByRole('heading', { name: '设置新密码' })).toBeVisible();
  await page.getByLabel('密码', { exact: true }).fill('New-password-2026');
  await page.getByLabel('确认密码').fill('not-the-same');
  await expect(page.getByText('两次输入的密码不一致')).toBeVisible();
  await expect(page.getByRole('button', { name: '更新密码' })).toBeDisabled();
  await page.getByLabel('确认密码').fill('New-password-2026');
  await page.getByRole('button', { name: '更新密码' }).click();
  await expect(page.getByText('密码已更新，请使用新密码登录。')).toBeVisible();
});

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

test('product acquisition exposes working link, extension, and screenshot paths', async ({ page }, testInfo) => {
  await page.goto('/');
  if (testInfo.project.name.includes('mobile')) {
    await page.locator('.mobile-nav').getByRole('button', { name: '对比', exact: true }).click();
  } else {
    await page.getByRole('button', { name: '智能对比', exact: true }).click();
  }
  await expect(page.getByRole('heading', { name: '把你正在纠结的商品交给 ValuSee' })).toBeVisible();

  await page.getByRole('button', { name: /粘贴商品链接/ }).click();
  await expect(page.getByRole('textbox', { name: '粘贴淘宝、京东、拼多多商品链接' })).toBeFocused();
  await expect(page.getByRole('link', { name: /安装浏览器扩展/ })).toHaveAttribute('href', '/api/v1/downloads/browser-extension');

  const chooserPromise = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: /上传商品截图/ }).click();
  const chooser = await chooserPromise;
  expect(chooser.isMultiple()).toBe(false);
});

test('an unreadable commerce page shows recovery actions instead of an empty candidate', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes('mobile'), 'covered once on desktop');
  let requestCount = 0;
  await page.route('**/api/v1/shopping/parse-url', async (route) => {
    requestCount += 1;
    await new Promise((resolve) => setTimeout(resolve, 150));
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        product: {
          title: '来自 淘宝 的商品（待确认）', platform: '淘宝', url: 'https://item.taobao.com/item.htm?id=778899',
          brand: '', model: '', sku: '', specs: { 商品ID: '778899' }, price: 0, coupon: 0,
          platform_discount: 0, member_discount: 0, subsidy: 0, pay_discount: 0, shipping: 0,
          gift_value: 0, official_store: false,
        },
        message: '公开页面未返回完整商品信息，请使用浏览器扩展、截图 OCR 或手动补充。',
        fetch_status: 'blocked', fallback_actions: ['browser_extension', 'screenshot_ocr', 'manual_confirmation'],
      }),
    });
  });
  await page.goto('/?view=analyze');
  const input = page.getByPlaceholder('粘贴淘宝、京东、拼多多商品链接');
  await input.fill('https://item.taobao.com/item.htm?id=778899');
  await page.getByRole('button', { name: '读取链接' }).click({ clickCount: 2 });

  await expect(page.getByText('淘宝公开页面没有返回可确认的商品信息')).toBeVisible();
  await expect(page.locator('.product-editor')).toHaveCount(0);
  expect(requestCount).toBe(1);
  await expect(page.getByRole('link', { name: '安装扩展采集' })).toBeVisible();
  await page.getByRole('button', { name: '手动补充' }).click();
  await expect(page.locator('.product-editor')).toHaveCount(1);
});
