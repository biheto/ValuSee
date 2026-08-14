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

  test('membership clearly shows paid services are unavailable', async ({ page }) => {
    await page.getByRole('button', { name: '我的', exact: true }).first().click();
    await page.getByRole('button', { name: /会员权益/ }).click();
    await expect(page.getByRole('heading', { name: '会员权益' })).toBeVisible();
    await expect(page.getByText('付费服务暂未开放，当前不会创建订单、扣款或激活付费会员。')).toBeVisible();
    const unavailable = page.getByRole('button', { name: '暂未开放' });
    await expect(unavailable).toBeDisabled();
    await expect(page.getByRole('button', { name: '创建月付订单' })).toHaveCount(0);
  });

  test('authorized commerce search displays sourced products and adds one to comparison', async ({ page }) => {
    await page.route('**/api/v1/shopping/search', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          query: '降噪耳机',
          sources: [{ provider: 'pdd', status: 'ok', count: 1 }],
          message: '结果来自已授权平台接口，价格和优惠可能变化，下单前请回到原平台核验。',
          results: [{
            provider: 'pdd',
            kind: 'official_affiliate',
            product: {
              title: '测试降噪耳机', platform: '拼多多', url: 'https://mobile.yangkeduo.com/goods.html?goods_id=123456',
              brand: 'TestAudio', model: '', sku: 'goods-sign-1', specs: { 类目: '耳机' }, price: 1599,
              coupon: 100, platform_discount: 0, member_discount: 0, subsidy: 0, pay_discount: 0,
              shipping: 0, gift_value: 0, condition: '新品', official_store: false, return_days: 7,
              warranty_months: 0, store_name: '测试官方旗舰店', image_url: '', notes: '官方接口测试商品',
            },
          }],
        }),
      });
    });

    await page.getByPlaceholder('搜索商品，例如：降噪耳机、27 英寸显示器').fill('降噪耳机');
    await page.getByRole('button', { name: '搜索商品' }).click();
    await expect(page.getByRole('heading', { name: '测试降噪耳机' })).toBeVisible();
    await expect(page.getByText('拼多多 · 测试官方旗舰店')).toBeVisible();
    await page.getByRole('button', { name: '加入对比' }).click();
    await expect(page.getByText(/商品已加入候选清单/)).toBeVisible();
    await page.getByRole('button', { name: '智能对比', exact: true }).click();
    await expect.poll(() => page.locator('input').evaluateAll((inputs) => inputs.some((input) => input.value === '测试降噪耳机'))).toBe(true);
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

test('smart comparison requires a tested personal LLM key', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes('mobile'), 'covered once on desktop');
  await page.goto('/?view=analyze');
  await expect(page.getByRole('button', { name: '配置个人 Key' })).toBeVisible();
  await expect(page.getByText('智能对比只使用你的个人 LLM Key')).toBeVisible();
  await page.getByRole('button', { name: '配置个人 Key' }).click();
  await expect(page.getByRole('heading', { name: '登录 ValuSee' })).toBeVisible();
});

test('shopping candidates survive refresh and report markdown renders as document structure', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes('mobile'), 'covered once on desktop');
  const product = {
    title: '刷新后仍保留的显示器', platform: '京东', url: 'https://item.jd.com/10001.html', brand: 'Example', model: 'M27', sku: 'M27-4K',
    specs: { 分辨率: '3840x2160' }, price: 1999, coupon: 100, platform_discount: 0, member_discount: 0, subsidy: 0, pay_discount: 0,
    shipping: 0, gift_value: 0, condition: 'new', official_store: true, return_days: 7, warranty_months: 36, notes: '',
  };
  await page.addInitScript(({ draftProduct }) => {
    localStorage.setItem('valuesee-shopping-draft:guest', JSON.stringify({ version: 1, goal: '比较 4K 显示器', budget: 2500, products: [draftProduct], updated_at: new Date().toISOString() }));
    localStorage.setItem('valuesee-last-report', JSON.stringify({
      task_id: 'task-markdown', status: 'completed', events: [], result: {
        best_index: 0, recommendation: 'buy', recommendation_reason: '规格适合当前需求。', summary: '建议购买候选 1',
        comparison_rows: [{ index: 0, title: draftProduct.title, platform: draftProduct.platform, model: draftProduct.model, same_item_relation: 'same', same_item_confidence: 1, final_price: 1899, value_score: 90, risk_level: 'low', suitable_for_user: true }],
        price_breakdowns: [{ final_price: 1899 }], risk_reports: [{ overall_risk: 'low', reasons: [] }],
        report_markdown: '## 购买建议\n\n- **到手价**：1899 元\n- 支持 4K\n\n> 下单前核对当前 SKU。',
      },
    }));
  }, { draftProduct: product });

  await page.goto('/?view=analyze');
  await expect(page.locator('.title-input')).toHaveValue('刷新后仍保留的显示器');
  await page.reload();
  await expect(page.locator('.title-input')).toHaveValue('刷新后仍保留的显示器');
  await page.getByText('查看完整决策报告').click();
  await expect(page.locator('.report-markdown').getByRole('heading', { name: '购买建议' })).toBeVisible();
  await expect(page.locator('.report-markdown').getByText('到手价')).toBeVisible();
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
