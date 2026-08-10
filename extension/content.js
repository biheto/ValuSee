(() => {
  const firstText = (selectors) => {
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      const value = node?.getAttribute('content') || node?.textContent;
      if (value?.trim()) return value.trim().replace(/\s+/g, ' ');
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
    if (host.includes('pinduoduo.com') || host.includes('yangkeduo.com')) return '拼多多';
    return host;
  };
  const productJson = () => {
    const visit = (value) => {
      if (Array.isArray(value)) return value.map(visit).find(Boolean);
      if (!value || typeof value !== 'object') return null;
      const type = value['@type'];
      if (type === 'Product' || Array.isArray(type) && type.includes('Product')) return value;
      return visit(value['@graph']);
    };
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      try { const found = visit(JSON.parse(script.textContent || '{}')); if (found) return found; } catch { /* malformed merchant data */ }
    }
    return {};
  };
  const selectedVariant = () => {
    const values = [];
    const selectors = [
      '[aria-checked="true"]', '[aria-selected="true"]',
      '.sku-item.selected', '.itemInfo-wrap .selected',
      '[class*=SkuItem][class*=selected]', '[class*=sku][class*=active]',
      '[class*=spec][class*=selected]', '[class*=spec][class*=active]'
    ];
    document.querySelectorAll(selectors.join(',')).forEach((node) => {
      const value = node.getAttribute('title') || node.textContent;
      const clean = value?.trim().replace(/\s+/g, ' ');
      if (clean && clean.length <= 80 && !values.includes(clean)) values.push(clean);
    });
    return values.slice(0, 8).join(' / ');
  };
  const specifications = () => {
    const specs = {};
    const add = (key, value) => {
      const cleanKey = String(key || '').trim().replace(/[：:]$/, '');
      const cleanValue = String(value || '').trim().replace(/\s+/g, ' ');
      if (cleanKey && cleanValue && cleanKey.length <= 50 && cleanValue.length <= 200 && Object.keys(specs).length < 20) specs[cleanKey] = cleanValue;
    };
    document.querySelectorAll('table tr').forEach((row) => {
      const cells = row.querySelectorAll('th,td');
      if (cells.length >= 2) add(cells[0].textContent, cells[1].textContent);
    });
    document.querySelectorAll('dl').forEach((list) => {
      const names = list.querySelectorAll('dt');
      const values = list.querySelectorAll('dd');
      names.forEach((name, index) => add(name.textContent, values[index]?.textContent));
    });
    document.querySelectorAll('[class*=parameter] li, [class*=attributes] li, .Ptable-item').forEach((node, index) => {
      const value = node.textContent?.trim().replace(/\s+/g, ' ');
      if (value && value.length < 200) {
        const parts = value.split(/[：:]/, 2);
        add(parts.length === 2 ? parts[0] : `页面规格${index + 1}`, parts.length === 2 ? parts[1] : value);
      }
    });
    return specs;
  };
  const canonicalUrl = () => {
    const url = new URL(location.href);
    const allowed = new Set(['id', 'item_id', 'sku', 'skuid', 'goods_id', 'goodsid']);
    [...url.searchParams.keys()].forEach((key) => { if (!allowed.has(key.toLowerCase())) url.searchParams.delete(key); });
    url.hash = '';
    return url.toString();
  };
  const collect = () => {
    const structured = productJson();
    const offers = structured.offers && !Array.isArray(structured.offers) ? structured.offers : {};
    const title = structured.name || firstText(['meta[property="og:title"]', '#name h1', '.tb-main-title', '.ItemHeader--mainTitle', '[class*=goodsName]', 'h1']) || document.title;
    const pagePriceText = firstText([
      'meta[property="product:price:amount"]', '.p-price .price', '.summary-price .p-price',
      '.tm-price', '.tb-rmb-num', '[class*=Price--priceText]', '[class*=priceWrap] [class*=price]',
      '[data-testid*=price]', '[class*=goodsPrice]'
    ]);
    const memberPriceText = firstText(['[class*=memberPrice]', '[class*=vipPrice]', '[class*=plus-price]', '[class*=Price][class*=member]']);
    const couponText = firstText(['[class*=coupon] [class*=price]', '[class*=Coupon] [class*=amount]', '.quan-item .text', '[class*=discountCoupon]']);
    const discountText = firstText(['[class*=promotion] [class*=price]', '[class*=Promotion] [class*=amount]', '.prom-item', '[class*=fullReduction]']);
    const storeName = structured.offers?.seller?.name || firstText(['.shopName', '#shop-name', '[class*=shopName]', '[class*=sellerName]', '[class*=storeName]']);
    const imageValue = Array.isArray(structured.image) ? structured.image[0] : structured.image;
    const imageUrl = imageValue || document.querySelector('meta[property="og:image"]')?.content || document.querySelector('#spec-img, [class*=mainPic] img, [class*=gallery] img')?.src || '';
    const params = new URL(location.href).searchParams;
    const sku = String(structured.sku || params.get('skuId') || params.get('id') || params.get('goods_id') || '');
    const variant = selectedVariant();
    const bodyText = document.body.innerText.slice(0, 200000);
    const region = firstText(['#areaAddress', '.ui-area-text', '[class*=deliveryAddress]', '[class*=region]']) || 'unknown';
    const hasMembership = Boolean(memberPriceText) || /PLUS会员|88VIP|会员价|省钱月卡/.test(bodyText);
    const price = number(pagePriceText || offers.price || offers.lowPrice || structured.price);
    const memberPrice = number(memberPriceText);
    const memberDiscount = memberPrice > 0 && price > memberPrice ? price - memberPrice : 0;
    return {
      title: String(title).slice(0, 200), category: 'unknown', platform: platform(), url: canonicalUrl(),
      brand: typeof structured.brand === 'object' ? String(structured.brand?.name || '') : String(structured.brand || ''),
      model: String(structured.model || structured.mpn || ''), sku, specs: specifications(), price,
      coupon: number(couponText), platform_discount: number(discountText), member_discount: memberDiscount,
      subsidy: 0, pay_discount: 0, shipping: 0, gift_value: 0, condition: 'new',
      official_store: /官方旗舰|官方店|京东自营|品牌直营/.test(bodyText), return_days: 7,
      warranty_months: 12, store_name: storeName, image_url: imageUrl,
      selected_variant: variant, region, membership: hasMembership ? '页面显示会员条件' : '未发现会员条件',
      observation_status: 'requires_confirmation',
      evidence: { type: 'browser_visible_page', url: canonicalUrl(), page_title: document.title, image_url: imageUrl },
      notes: '由 ValuSee 扩展读取当前可见页面；发送前请确认 SKU、地区、会员资格、优惠和价格。'
    };
  };
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === 'VALUSee_COLLECT_PRODUCT') sendResponse({ ok: true, product: collect() });
  });
})();
