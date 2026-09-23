import { expect, test, type Page } from '@playwright/test';

async function register(page: Page) {
  const email = `copilot-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`;
  const captchaResponsePromise = page.waitForResponse((response) => response.url().includes('/api/v1/auth/captcha'));
  await page.goto('/register');
  const captchaResponse = await captchaResponsePromise;
  await page.getByLabel('昵称').fill('Copilot Tester');
  await page.getByLabel('邮箱', { exact: true }).fill(email);
  await page.getByRole('button', { name: '获取验证码' }).click();
  await expect(page.getByLabel('邮箱验证码')).toHaveValue(/^\d{6}$/);
  const captcha = await captchaResponse.json();
  await page.getByLabel('图形验证码输入').fill(captcha.code);
  await page.getByLabel('密码', { exact: true }).fill('E2e-password-2026');
  await page.getByLabel('确认密码').fill('E2e-password-2026');
  await page.getByRole('button', { name: '注册并登录' }).click();
  await expect(page.getByRole('button', { name: 'Copilot Tester' })).toBeVisible();
}

test.describe('shopping copilot page', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name.includes('mobile'), 'desktop copilot suite');
    await register(page);
  });

  test('shows a shopping guide workspace with sources and follow-up search', async ({ page }) => {
    await page.route('**/api/v1/shopping/copilot/chat', async (route) => {
      const body = route.request().postDataJSON() as { message?: string };
      const query = String(body.message || '');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          query,
          search_query: query,
          answer: `### 我先帮你搜了一轮\n\n搜索结果来自授权来源，并核对了实时网页资料。[1]`,
          answer_source: 'llm',
          model: 'test-model',
          sources: [
            { source_type: 'commerce', provider: 'jd', status: 'ok', count: 2 },
            { source_type: 'web', provider: 'tavily', status: 'ok', count: 1 },
            { source_type: 'rag', provider: 'shopping-knowledge', status: 'ok', count: 2 },
            { source_type: 'model', provider: 'test-model', status: 'ok', count: 1 },
          ],
          citations: [{ id: 1, source_type: 'web', provider: 'tavily', title: '显示器官方规格', url: 'https://example.com/monitor', domain: 'example.com', snippet: '27 英寸显示器官方规格', published_at: '2026-09-20', fetched_at: '2026-09-23T10:00:00Z', score: 0.91 }],
          rag_results: [{ chunk_id: 'sku-1', path: 'shopping/monitor.md', content: '显示器选购规则', score: 0.8 }],
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
    await expect(page.getByRole('heading', { name: '新的购物对话' })).toBeVisible();
    await expect(page.locator('.copilot-message.assistant').filter({ hasText: '欢迎来到 ValuSee AI 导购' })).toBeVisible();

    const composer = page.getByPlaceholder('例如：给我找一台适合代码办公的 27 英寸显示器，预算 2500 元');
    await composer.fill('帮我找一台适合代码办公的 27 英寸显示器，预算 2500 元');
    await page.getByRole('button', { name: '发送' }).click();

    await expect(page.locator('.copilot-message.assistant').filter({ hasText: '我先帮你搜了一轮' })).toBeVisible();
    await expect(page.locator('.copilot-source-strip').first()).toContainText('京东 · 2 条');
    await expect(page.locator('.copilot-citations').first()).toContainText('显示器官方规格');
    await expect(page.locator('.copilot-citations a').first()).toHaveAttribute('href', 'https://example.com/monitor');
    await expect(page.locator('.copilot-source-board')).toContainText('京东');
    await expect(page.locator('.copilot-followup-board')).toContainText('只看官方店');
    await expect(page.locator('.copilot-evidence-board')).toContainText('旗舰款');
    await expect(page.getByRole('button', { name: '加入对比' }).first()).toBeVisible();

    await page.locator('.copilot-collapse').first().click();
    await expect(page.locator('.copilot-message.is-collapsed')).toHaveCount(1);
    await page.locator('.copilot-collapse').first().click();

    await page.locator('.copilot-pills button').filter({ hasText: '只看官方店' }).click();
    await expect(page.locator('.copilot-message.user')).toHaveCount(2);
    await expect(async () => {
      const count = await page.getByText(/搜索结果来自授权来源/).count();
      expect(count).toBeGreaterThanOrEqual(2);
    }).toPass();

    await page.getByRole('button', { name: '加入对比' }).first().click();
    await expect(page.getByText(/已加入候选/)).toBeVisible();
    await expect(page.getByRole('button', { name: /对比工作台/ })).toBeEnabled();
  });

  test('starts a usable new conversation while the previous response is pending', async ({ page }) => {
    let requestCount = 0;
    let releaseFirstRequest: (() => void) | undefined;
    await page.route('**/api/v1/shopping/copilot/chat', async (route) => {
      requestCount += 1;
      const currentRequest = requestCount;
      const body = route.request().postDataJSON() as { message?: string };
      const query = String(body.message || '');
      if (currentRequest === 1) {
        await new Promise<void>((resolve) => { releaseFirstRequest = resolve; });
      } else {
        releaseFirstRequest?.();
      }
      try {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            query,
            search_query: query,
            answer: `回答：${query}`,
            answer_source: 'llm',
            model: 'test-model',
            sources: [],
            citations: [],
            rag_results: [],
            message: '',
            results: [],
          }),
        });
      } catch {
        // Ignore a route closing with the page during test teardown.
      }
    });

    await page.goto('/?view=copilot');
    const composer = page.getByPlaceholder('例如：给我找一台适合代码办公的 27 英寸显示器，预算 2500 元');
    await composer.fill('旧对话指令');
    await page.getByRole('button', { name: '发送' }).click();
    await expect(page.locator('.copilot-message.is-loading')).toBeVisible();

    await page.getByRole('button', { name: '开启新对话' }).click();
    await expect(composer).toBeFocused();
    await expect(page.locator('.copilot-message.user')).toHaveCount(0);
    await composer.fill('新对话指令');
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await expect(page.locator('.copilot-message.assistant').filter({ hasText: '回答：新对话指令' })).toBeVisible();
    await expect(page.locator('.copilot-list').getByText('回答：旧对话指令')).toHaveCount(0);

    const oldThread = page.locator('.copilot-thread-list button').filter({ hasText: '旧对话指令' });
    await expect(oldThread).toBeVisible();
    await oldThread.click();
    await expect(page.locator('.copilot-message.assistant').filter({ hasText: '回答：旧对话指令' })).toBeVisible();
    await expect(page.getByText('已停止生成')).toHaveCount(0);
  });

  test('can stop a pending response and continue in the same conversation', async ({ page }) => {
    let releaseRequest: (() => void) | undefined;
    let requestCount = 0;
    await page.route('**/api/v1/shopping/copilot/chat', async (route) => {
      requestCount += 1;
      const body = route.request().postDataJSON() as { message?: string };
      const query = String(body.message || '');
      if (requestCount === 1) {
        await new Promise<void>((resolve) => { releaseRequest = resolve; });
      }
      try {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            query,
            search_query: query,
            answer: `回答：${query}`,
            answer_source: 'llm',
            model: 'test-model',
            sources: [],
            citations: [],
            rag_results: [],
            message: '',
            results: [],
          }),
        });
      } catch {
        // A stopped browser request can close before the mocked response is released.
      }
    });

    await page.goto('/?view=copilot');
    const composer = page.getByPlaceholder('例如：给我找一台适合代码办公的 27 英寸显示器，预算 2500 元');
    await composer.fill('需要停止的指令');
    await page.getByRole('button', { name: '发送' }).click();
    const stopButton = page.getByRole('button', { name: '停止', exact: true });
    await expect(stopButton).toBeVisible();
    await stopButton.click();

    await expect(page.locator('.copilot-message.is-stopped')).toContainText('已停止生成');
    await expect(composer).toBeFocused();
    await composer.fill('停止后的新指令');
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeEnabled();
    releaseRequest?.();
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await expect(page.locator('.copilot-message.assistant').filter({ hasText: '回答：停止后的新指令' })).toBeVisible();
  });

  test('keeps capability details inside the modal and can collapse the conversation rail', async ({ page }) => {
    await page.goto('/?view=copilot');

    const navigation = page.locator('.app-header');
    const navigationToggle = page.getByRole('button', { name: '隐藏功能导航' });
    const initialNavigationWidth = (await navigation.boundingBox())?.width || 0;
    await navigationToggle.click();
    await expect(page.getByRole('button', { name: '展开功能导航' })).toBeVisible();
    await expect.poll(async () => (await navigation.boundingBox())?.width || 0).toBe(0);
    await page.getByRole('button', { name: '展开功能导航' }).click();
    await expect.poll(async () => (await navigation.boundingBox())?.width || 0).toBeGreaterThan(0);

    const edgeControl = page.locator('.app-nav-edge-control');
    const edgeBox = await edgeControl.boundingBox();
    expect(edgeBox).not.toBeNull();
    if (edgeBox) {
      const startX = edgeBox.x + edgeBox.width / 2;
      await edgeControl.dispatchEvent('pointerdown', { clientX: startX, pointerId: 1 });
      await page.evaluate((clientX) => window.dispatchEvent(new PointerEvent('pointermove', { clientX, pointerId: 1 })), startX + 38);
      await page.evaluate(() => window.dispatchEvent(new PointerEvent('pointerup', { pointerId: 1 })));
      await expect.poll(async () => (await navigation.boundingBox())?.width || 0).toBeGreaterThan(initialNavigationWidth + 20);
    }

    const modeTrigger = page.locator('.copilot-context-actions .copilot-mode-trigger');
    await expect(modeTrigger).toContainText('当前');
    await modeTrigger.click();
    await expect(page.locator('.copilot-mode-selected')).toContainText('当前模式');
    await page.locator('.copilot-mode-modal button').filter({ hasText: '研究模式' }).click();
    await expect(modeTrigger).toContainText('研究模式');

    const rail = page.locator('.copilot-thread-rail');
    const railToggle = page.locator('.copilot-top-actions button').first();
    await railToggle.click();
    await expect.poll(async () => (await rail.boundingBox())?.width || 0).toBe(0);
    await railToggle.click();
    await expect.poll(async () => (await rail.boundingBox())?.width || 0).toBeGreaterThan(0);

    await page.locator('.copilot-context-actions button').filter({ hasText: 'AI' }).click();
    await expect(page.locator('.copilot-modal')).toBeVisible();
    await expect(page.locator('.copilot-modal-capabilities')).toBeVisible();

    const firstCapability = page.locator('.copilot-modal-capability').first();
    const firstCapabilityName = await firstCapability.locator('strong').textContent();
    await firstCapability.click();
    await expect(page.locator('.copilot-modal-capability-detail')).toBeVisible();
    await expect(page.locator('.copilot-capability-popover')).toHaveCount(0);
    await expect(page.locator('.copilot-modal h2')).not.toHaveText('AI 鑳藉姟鍦板浘');

    await page.getByRole('button', { name: '返回能力列表' }).click();
    await expect(page.locator('.copilot-modal-capabilities')).toBeVisible();
    await expect(page.locator('.copilot-modal-search')).toBeVisible();
    await expect(page.locator('.copilot-modal-capability').first().locator('strong')).toHaveText(firstCapabilityName || '');
  });
});
