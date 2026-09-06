import { expect, test, type Page } from '@playwright/test';

async function register(page: Page) {
  const email = `copilot-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`;
  await page.goto('/');
  await page.getByRole('button', { name: '本地账户' }).click();
  await page.getByRole('button', { name: '没有账户？立即注册' }).click();
  await page.getByLabel('昵称').fill('Copilot Tester');
  await page.getByLabel('邮箱', { exact: true }).fill(email);
  await page.getByRole('button', { name: '获取验证码' }).click();
  await expect(page.getByLabel('邮箱验证码')).toHaveValue(/^\d{6}$/);
  await page.getByLabel('密码', { exact: true }).fill('E2e-password-2026');
  await page.getByLabel('确认密码').fill('E2e-password-2026');
  await page.getByRole('button', { name: '注册', exact: true }).click();
  await expect(page.getByText('邮箱验证完成，账户创建成功。')).toBeVisible();
}

test.describe('shopping copilot page', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name.includes('mobile'), 'desktop copilot suite');
    await register(page);
  });

  test('shows a shopping guide workspace with sources and follow-up search', async ({ page }) => {
    await page.route('**/api/v1/shopping/search', async (route) => {
      const body = route.request().postDataJSON() as { query?: string };
      const query = String(body.query || '');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          query,
          sources: [
            { provider: 'jd', status: 'ok', count: 2 },
            { provider: 'pdd', status: 'ok', count: 1 },
          ],
          message: '搜索结果来自授权来源，价格和来源在下单前仍要回到原页面核验。',
          results: [
            {
              provider: 'jd',
              kind: 'official_affiliate',
              product: {
                title: `${query || '测试商品'} 旗舰款`,
                platform: '京东',
                url: 'https://item.jd.com/10001.html',
                brand: 'ValuSee',
                model: 'VS-27',
                sku: 'VS27-01',
                specs: { 尺寸: '27 英寸', 分辨率: '2560x1440' },
                price: 1999,
                coupon: 200,
                platform_discount: 80,
                member_discount: 0,
                subsidy: 0,
                pay_discount: 0,
                shipping: 0,
                gift_value: 0,
                condition: '新品',
                official_store: true,
                return_days: 7,
                warranty_months: 36,
                store_name: '京东自营',
                image_url: '',
                notes: '授权接口测试商品',
              },
            },
          ],
        }),
      });
    });

    await page.goto('/?view=copilot');
    await expect(page.getByRole('heading', { name: '像专业导购一样追问购物需求' })).toBeVisible();
    await expect(page.getByText('欢迎来到 ValuSee AI 导购')).toBeVisible();

    const composer = page.getByPlaceholder('例如：给我找一台适合代码办公的 27 英寸显示器，预算 2500 元');
    await composer.fill('帮我找一台适合代码办公的 27 英寸显示器，预算 2500 元');
    await page.getByRole('button', { name: '发送' }).click();

    await expect(page.getByText('我先帮你搜了一轮')).toBeVisible();
    await expect(page.locator('.copilot-source-strip').first()).toContainText('京东 · 2 条');
    await expect(page.locator('.copilot-source-board')).toContainText('京东');
    await expect(page.locator('.copilot-followup-board')).toContainText('只看官方店');
    await expect(page.locator('.copilot-evidence-board')).toContainText('旗舰款');
    await expect(page.getByRole('button', { name: '加入对比' }).first()).toBeVisible();

    await page.locator('.copilot-collapse').first().click();
    await expect(page.locator('.copilot-message.is-collapsed')).toHaveCount(1);
    await page.locator('.copilot-collapse').first().click();

    await page.locator('.copilot-pills button').first().click();
    await expect(page.locator('.copilot-message.user')).toHaveCount(2);
    await expect(async () => {
      const count = await page.getByText(/搜索结果来自授权来源/).count();
      expect(count).toBeGreaterThanOrEqual(2);
    }).toPass();

    await page.getByRole('button', { name: '加入对比' }).first().click();
    await expect(page.getByText(/已加入候选/)).toBeVisible();
    await expect(page.locator('.copilot-sidebar-actions').getByRole('button', { name: '去对比工作台' })).toBeEnabled();
  });
});
