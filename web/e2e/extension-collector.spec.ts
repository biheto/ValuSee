import { expect, test } from '@playwright/test';
import path from 'node:path';

type Capture = {
  ok: boolean;
  product: {
    platform: string;
    title: string;
    price: number;
    sku: string;
    selected_variant: string;
    store_name: string;
    specs: Record<string, string | number>;
  };
  diagnostics: { missing: string[] };
};

const collectorPath = path.resolve(process.cwd(), '../extension/content.js');

async function captureFixture(page: import('@playwright/test').Page, url: string, html: string): Promise<Capture> {
  await page.addInitScript(() => {
    const target = window as typeof window & { __valueseeListener?: (...args: unknown[]) => void; chrome?: unknown };
    target.chrome = {
      runtime: {
        onMessage: {
          addListener(listener: (...args: unknown[]) => void) { target.__valueseeListener = listener; },
        },
      },
    };
  });
  await page.route(url, (route) => route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: html }));
  await page.goto(url);
  await page.addScriptTag({ path: collectorPath });
  return page.evaluate(() => {
    const target = window as typeof window & { __valueseeListener?: (...args: unknown[]) => void };
    let captured: Capture | undefined;
    target.__valueseeListener?.({ type: 'VALUSee_COLLECT_PRODUCT_V3' }, {}, (response: Capture) => { captured = response; });
    if (!captured) throw new Error('collector did not respond');
    return captured;
  });
}

test('collects the visible JD product and selected SKU', async ({ page }) => {
  const result = await captureFixture(page, 'https://item.jd.com/100092233.html', `
    <html><head><meta property="og:image" content="https://img.example/jd.jpg"></head><body>
      <h1 class="sku-name">联想 ThinkBook 14+ 笔记本电脑</h1>
      <div class="p-price"><span class="price">5299.00</span></div>
      <div id="shop-name">联想京东自营旗舰店</div>
      <button class="sku-item selected" title="32GB / 1TB">32GB / 1TB</button>
      <script>window.pageConfig={"product":{"skuid":100092233}};</script>
    </body></html>`);

  expect(result.ok).toBeTruthy();
  expect(result.product).toMatchObject({ platform: '京东', title: '联想 ThinkBook 14+ 笔记本电脑', price: 5299, sku: '100092233', selected_variant: '32GB / 1TB' });
  expect(result.diagnostics.missing).toEqual([]);
});

test('collects Taobao rendered price and embedded SKU', async ({ page }) => {
  const result = await captureFixture(page, 'https://item.taobao.com/item.htm?id=778899', `
    <html><body>
      <h1 class="ItemHeader--mainTitle">Sony WH-1000XM5 无线降噪耳机</h1>
      <span class="Price--priceText">¥ 2,499.00</span>
      <div class="J_TSaleProp"><button class="tb-selected">黑色</button></div>
      <script>window.__ITEM_DATA__={"skuId":"XM5-BLACK"};</script>
    </body></html>`);

  expect(result.product).toMatchObject({ platform: '淘宝', price: 2499, sku: 'XM5-BLACK', selected_variant: '黑色' });
  expect(result.diagnostics.missing).toEqual([]);
});

test('collects Taobao effective price and ignores review-title noise', async ({ page }) => {
  const result = await captureFixture(page, 'https://item.taobao.com/item.htm?id=5807786724999', `
    <html><head><title>小个子工装牛仔背带裤女宽松慵懒风 - 淘宝</title></head><body>
      <div class="ItemTitle--commentSummary">用户评价·400+</div>
      <h1 class="ItemHeader--mainTitle">小个子工装牛仔背带裤短裤女宽松慵懒风可爱减龄学生2026新款夏日</h1>
      <section class="Price--root">
        <span class="Price--priceText">优惠前 ¥98</span>
        <strong>券后 ¥83.26</strong>
        <span>官方立减12%省11.8元</span><span>淘金币已抵2.94元</span>
      </section>
      <div class="ShopHeader--root"><a class="ShopHeader--title">WAN 小婉女装·4.988VIP好评率95%平均13小时发货客服满意度95%</a></div>
      <section class="SkuContent--root"><span>颜色分类</span><button class="SkuContent--valueItem SkuContent--valueItemActive">千人加购 牛仔蓝 优质现货</button></section>
      <script>window.__ITEM_DATA__={"skuId":"5807786724999"};</script>
    </body></html>`);

  expect(result.product).toMatchObject({
    platform: '淘宝',
    title: '小个子工装牛仔背带裤短裤女宽松慵懒风可爱减龄学生2026新款夏日',
    price: 83.26,
    sku: '5807786724999',
    selected_variant: '牛仔蓝 优质现货',
    store_name: 'WAN 小婉女装',
  });
  expect(result.product.specs).toMatchObject({ 价格口径: '页面券后/到手价，已包含页面展示优惠', 优惠前价格: 98 });
  expect(result.diagnostics.missing).toEqual([]);
});

test('collects Pinduoduo raw data and normalizes cent price', async ({ page }) => {
  const result = await captureFixture(page, 'https://mobile.yangkeduo.com/goods.html?goods_id=66889900', `
    <html><body>
      <script>window.rawData={"goods":{"goodsName":"石头扫地机器人 P20 Pro","goodsId":66889900,"minGroupPrice":259900}};</script>
      <button class="SkuItem selected">白色</button>
    </body></html>`);

  expect(result.product).toMatchObject({ platform: '拼多多', title: '石头扫地机器人 P20 Pro', price: 2599, sku: '66889900', selected_variant: '白色' });
  expect(result.diagnostics.missing).toEqual([]);
});
