(() => {
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value) return value;
    }
    return '';
  };
  const number = (value) => {
    const match = String(value || '').replace(/,/g, '').match(/\d+(?:\.\d{1,2})?/);
    return match ? Number(match[0]) : 0;
  };
  const platform = () => {
    const host = location.hostname;
    if (host.includes('jd.com')) return '京东';
    if (host.includes('tmall.com')) return '天猫';
    if (host.includes('taobao.com')) return '淘宝';
    if (host.includes('pinduoduo.com')) return '拼多多';
    return host;
  };
  const collect = () => {
    const title = text(['#name h1', '.tb-main-title', '.ItemHeader--mainTitle', '[class*=goodsName]', 'h1']) || document.title;
    const priceText = text(['.p-price .price', '.tm-price', '.tb-rmb-num', '[class*=priceWrap] [class*=price]', '[class*=price]']);
    const model = text(['#detail .Ptable-item:nth-child(1) dd', '[class*=skuName]', '[class*=model]', '[data-property*=型号]']);
    const specs = {};
    document.querySelectorAll('[class*=sku], [class*=spec], .Ptable-item').forEach((node) => {
      const value = node.textContent?.trim().replace(/\s+/g, ' ');
      if (value && value.length < 120 && Object.keys(specs).length < 8) specs[`页面规格${Object.keys(specs).length + 1}`] = value;
    });
    return {
      title, platform: platform(), url: location.href, brand: '', model, sku: '', specs,
      price: number(priceText), coupon: 0, platform_discount: 0, member_discount: 0,
      subsidy: 0, pay_discount: 0, shipping: 0, gift_value: 0, condition: 'new',
      official_store: /官方|自营|旗舰/.test(document.body.innerText), return_days: 7,
      warranty_months: 12, notes: '由 ValuSee 浏览器扩展读取当前可见页面，请确认动态优惠和规格。'
    };
  };
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === 'VALUSee_COLLECT_PRODUCT') sendResponse({ ok: true, product: collect() });
  });
})();
