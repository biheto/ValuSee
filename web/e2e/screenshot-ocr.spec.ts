import { expect, test } from '@playwright/test';

test('on-device OCR turns a screenshot into a structured product candidate', async ({ page, context }, testInfo) => {
  test.setTimeout(90_000);
  const source = await context.newPage();
  await source.setViewportSize({ width: 1200, height: 800 });
  await source.setContent(`
    <main style="font-family:Arial,sans-serif;color:#111;background:#fff;padding:70px;width:1200px;height:800px">
      <p style="font-size:28px">JD Product Detail</p>
      <h1 style="font-size:46px;margin:48px 0">Apple AirPods Pro 2 USB-C</h1>
      <p style="font-size:32px">SKU: MTJV3CH/A</p>
      <p style="font-size:32px">Current price: RMB 1499</p>
      <p style="font-size:32px">Coupon: RMB 100</p>
      <p style="font-size:32px">Selected: White China Version</p>
    </main>`);
  const screenshot = await source.screenshot({ type: 'png' });
  await source.close();

  await page.goto('/');
  if (testInfo.project.name.includes('mobile')) {
    await page.locator('.mobile-nav').getByRole('button', { name: '对比', exact: true }).click();
  } else {
    await page.getByRole('button', { name: '智能对比', exact: true }).click();
  }
  await page.locator('.upload-button input[type=file]').setInputFiles({
    name: 'product-screenshot.png', mimeType: 'image/png', buffer: screenshot,
  });

  await expect(page.getByText(/截图文字已在你的浏览器中识别/)).toBeVisible({ timeout: 75_000 });
  const candidate = page.locator('.product-editor').last();
  await expect(candidate.locator('.title-input')).toHaveValue(/Apple AirPods Pro 2 USB-C/i);
  await expect(candidate.getByLabel('页面价格')).toHaveValue('1499');
  await expect(candidate.getByLabel('SKU')).toHaveValue(/MTJV3CH\/A/i);
});

test('on-device OCR reads a Chinese commerce screenshot', async ({ page, context }, testInfo) => {
  test.skip(testInfo.project.name.includes('mobile'), 'Chinese OCR coverage only needs one browser viewport');
  test.setTimeout(90_000);
  const source = await context.newPage();
  await source.setViewportSize({ width: 1200, height: 800 });
  await source.setContent(`
    <main style="font-family:'Microsoft YaHei',Arial,sans-serif;color:#111;background:#fff;padding:70px;width:1200px;height:800px">
      <p style="font-size:30px">京东商城 商品详情</p>
      <h1 style="font-size:44px;margin:46px 0">Apple AirPods Pro 2 USB-C 主动降噪耳机</h1>
      <p style="font-size:34px">商品编号: MTJV3CH/A</p>
      <p style="font-size:34px">当前价格: ¥1499</p>
      <p style="font-size:34px">优惠券: ¥100</p>
      <p style="font-size:34px">已选: USB-C 国行 白色</p>
    </main>`);
  const screenshot = await source.screenshot({ type: 'png' });
  await source.close();

  await page.goto('/');
  await page.getByRole('button', { name: '智能对比', exact: true }).click();
  await page.locator('.upload-button input[type=file]').setInputFiles({
    name: 'jd-screenshot.png', mimeType: 'image/png', buffer: screenshot,
  });

  await expect(page.getByText(/截图文字已在你的浏览器中识别/)).toBeVisible({ timeout: 75_000 });
  const candidate = page.locator('.product-editor').last();
  await expect(candidate.locator('.title-input')).toHaveValue(/AirPods Pro 2 USB-C/);
  await expect(candidate.getByLabel('平台', { exact: true })).toHaveValue('京东');
  await expect(candidate.getByLabel('页面价格')).toHaveValue('1499');
  await expect(candidate.getByLabel('SKU')).toHaveValue(/MTJV3CH\/A/i);
});
