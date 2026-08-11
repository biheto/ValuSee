(() => {
  if (window.__VALUSeeCollectorV4) return;
  window.__VALUSeeCollectorV4 = true;

  const clean = (value) => String(value || '').trim().replace(/\s+/g, ' ');
  const firstText = (selectors) => {
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      const value = node?.getAttribute('content') || node?.getAttribute('data-price') || node?.textContent;
      if (clean(value)) return clean(value);
    }
    return '';
  };
  const bestTitle = (structuredTitle, embeddedTitle, selectors) => {
    const candidates = [];
    const add = (raw, score, node = null) => {
      const value = clean(raw).replace(/\s*[-_|·]\s*(?:淘宝网?|天猫|京东|拼多多)\s*$/i, '');
      if (value.length < 5 || value.length > 200) return;
      if (/用户评价|宝贝评价|累计评价|全部评价|已售\s*\d|多人评价|加购|购物车|收藏夹|免费开店|帮助中心|搜索本店|搜索$|网页无障碍/i.test(value)) return;
      if (/^(?:淘宝网?|天猫|京东|拼多多|商品详情|店铺首页)$/i.test(value)) return;
      let finalScore = score + Math.min(value.length, 100) / 12;
      if (node?.matches?.('h1')) finalScore += 20;
      const className = String(node?.className || '');
      if (/mainTitle|itemTitle|productTitle|goodsName/i.test(className)) finalScore += 8;
      candidates.push({ value, score: finalScore });
    };
    add(structuredTitle, 40);
    add(embeddedTitle, 24);
    selectors.forEach((selector, index) => {
      document.querySelectorAll(selector).forEach((node, nodeIndex) => {
        if (nodeIndex < 40) add(node.getAttribute('content') || node.textContent, Math.max(2, 14 - index * 0.5), node);
      });
    });
    add(document.title, 1);
    return candidates.sort((left, right) => right.score - left.score)[0]?.value || '';
  };
  const number = (value) => {
    const matches = clean(value).replace(/,/g, '').match(/\d+(?:\.\d{1,2})?/g);
    if (!matches?.length) return 0;
    return Number(matches[matches.length - 1]);
  };
  const firstNumber = (value) => {
    const match = clean(value).replace(/,/g, '').match(/\d+(?:\.\d{1,2})?/);
    return match ? Number(match[0]) : 0;
  };
  const labeledNumber = (value, labels) => {
    const normalized = clean(value).replace(/,/g, '');
    for (const label of labels) {
      const match = normalized.match(new RegExp(`(?:${label})\\s*(?:约|低至)?\\s*[¥￥]?\\s*(\\d+(?:\\.\\d{1,2})?)`, 'i'));
      if (match) return Number(match[1]);
    }
    return 0;
  };
  const host = location.hostname.toLowerCase();
  const platform = () => {
    if (host === 'jd.com' || host.endsWith('.jd.com')) return '京东';
    if (host === 'tmall.com' || host.endsWith('.tmall.com')) return '天猫';
    if (host === 'taobao.com' || host.endsWith('.taobao.com')) return '淘宝';
    if (host.includes('pinduoduo.com') || host.includes('yangkeduo.com')) return '拼多多';
    return host;
  };
  const scriptText = () => Array.from(document.scripts).map((node) => node.textContent || '').filter(Boolean).join('\n').slice(0, 3000000);
  const decodeJsString = (value) => {
    try { return JSON.parse(`"${value}"`); }
    catch { return value.replace(/\\u([0-9a-f]{4})/gi, (_, code) => String.fromCharCode(parseInt(code, 16))).replace(/\\\//g, '/'); }
  };
  const embeddedString = (source, keys) => {
    for (const key of keys) {
      const pattern = new RegExp(`["']${key}["']\\s*:\\s*["']((?:\\\\.|[^"'\\\\]){1,500})["']`, 'i');
      const match = source.match(pattern);
      if (match) return clean(decodeJsString(match[1]));
      const scalar = source.match(new RegExp(`["']${key}["']\\s*:\\s*(\\d{1,100})(?=\\s*[,}])`, 'i'));
      if (scalar) return scalar[1];
    }
    return '';
  };
  const embeddedNumber = (source, keys) => {
    for (const key of keys) {
      const pattern = new RegExp(`["']${key}["']\\s*:\\s*(?:["'])?(\\d+(?:\\.\\d{1,2})?)(?:["'])?`, 'i');
      const match = source.match(pattern);
      if (match) {
        const value = Number(match[1]);
        return /(?:minGroupPrice|minNormalPrice|priceInCent)/i.test(key) && value >= 1000 ? value / 100 : value;
      }
    }
    return 0;
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
      try { const found = visit(JSON.parse(script.textContent || '{}')); if (found) return found; }
      catch { /* Merchant JSON-LD can be malformed. */ }
    }
    return {};
  };
  const profile = () => {
    const common = {
      title: ['meta[property="og:title"]', 'meta[name="twitter:title"]', 'h1'],
      price: ['meta[property="product:price:amount"]', 'meta[property="og:price:amount"]', '[itemprop="price"]'],
      store: ['[class*="shopName"]', '[class*="sellerName"]', '[class*="storeName"]'],
      image: ['meta[property="og:image"]', '[class*="gallery"] img', '[class*="mainPic"] img'],
      region: ['[class*="deliveryAddress"]', '[class*="delivery-address"]', '[class*="region"]'],
    };
    if (platform() === '京东') return {
      ...common,
      title: ['.sku-name', '#name h1', '[class*="sku-name"]', ...common.title],
      price: ['.summary-price .p-price .price', '.p-price .price', '[class*="price-now"]', '[class*="price"] [class*="num"]', ...common.price],
      store: ['#shop-name', '.popbox-inner .name', '[class*="shop-name"]', ...common.store],
      image: ['#spec-img', '#preview img', ...common.image],
      region: ['#areaAddress', '.ui-area-text', '#stock-address', ...common.region],
    };
    if (platform() === '淘宝' || platform() === '天猫') return {
      ...common,
      title: ['.ItemHeader--mainTitle', '[class*="ItemTitle"]', '.tb-main-title', '.tb-detail-hd h1', ...common.title],
      price: ['[class*="Price--priceText"]', '[class*="Price"] [class*="priceText"]', '.tm-price', '.tb-rmb-num', ...common.price],
      store: ['[class*="ShopHeader"] [class*="title"]', '.shop-name', ...common.store],
      image: ['[class*="PicGallery"] img', '#J_ImgBooth', ...common.image],
      region: ['[class*="Delivery"] [class*="address"]', ...common.region],
    };
    return {
      ...common,
      title: ['[class*="goodsName"]', '[class*="GoodsName"]', '[class*="goods-name"]', ...common.title],
      price: ['[class*="groupPrice"]', '[class*="salePrice"]', '[class*="goodsPrice"]', '[class*="price"] [class*="price"]', ...common.price],
      store: ['[class*="mallName"]', '[class*="MallName"]', '[class*="shop-name"]', ...common.store],
      image: ['[class*="goods-img"] img', '[class*="GoodsGallery"] img', ...common.image],
    };
  };
  const selectedVariant = () => {
    const values = [];
    const selectors = [
      '[aria-checked="true"]', '[aria-selected="true"]',
      '.sku-item.selected', '.itemInfo-wrap .selected', '.J_TSaleProp .tb-selected',
      '[class*="SkuItem"][class*="selected"]', '[class*="SkuItem"][class*="active"]',
      '[class*="sku"][class*="selected"]', '[class*="sku"][class*="active"]',
      '[class*="spec"][class*="selected"]', '[class*="spec"][class*="active"]',
      '[class*="sku" i][class*="selected" i]', '[class*="sku" i][class*="active" i]',
      '[class*="sku" i][class*="checked" i]', '[class*="valueItem" i][class*="active" i]',
      '[class*="valueItem" i][class*="selected" i]',
    ];
    document.querySelectorAll(selectors.join(',')).forEach((node) => {
      const value = node.getAttribute('title') || node.getAttribute('aria-label') || node.textContent;
      const normalized = clean(value).replace(/千人加购|已选中?|当前选择/gi, '').trim();
      if (normalized && normalized.length <= 80 && !/^(?:颜色分类|尺码|规格)$/.test(normalized) && !values.includes(normalized)) values.push(normalized);
    });
    return values.slice(0, 8).join(' / ');
  };
  const storeName = (value) => clean(value)
    .split(/(?:·|\||丨)?\s*\d+(?:\.\d+)?\s*VIP|好评率|平均\s*\d|客服满意度|粉丝\s*\d/i)[0]
    .replace(/\s*(?:客服|进店)\s*$/g, '')
    .trim()
    .slice(0, 100);
  const specifications = () => {
    const specs = {};
    const add = (key, value) => {
      const cleanKey = clean(key).replace(/[：:]$/, '');
      const cleanValue = clean(value);
      if (cleanKey && cleanValue && cleanKey.length <= 50 && cleanValue.length <= 200 && Object.keys(specs).length < 24) specs[cleanKey] = cleanValue;
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
    document.querySelectorAll('[class*=parameter] li, [class*=attributes] li, .Ptable-item, #detail .p-parameter li').forEach((node, index) => {
      const value = clean(node.textContent);
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
  const identity = () => {
    const params = new URL(location.href).searchParams;
    const queryId = params.get('skuId') || params.get('sku') || params.get('id') || params.get('item_id') || params.get('goods_id') || params.get('goodsId');
    if (queryId) return queryId;
    if (platform() === '京东') return location.pathname.match(/\/(\d{5,})(?:\.html)?/)?.[1] || '';
    return '';
  };
  const collect = () => {
    const selectors = profile();
    const source = scriptText();
    const structured = productJson();
    const offers = structured.offers && !Array.isArray(structured.offers) ? structured.offers : {};
    const embeddedTitle = embeddedString(source, ['itemTitle', 'rawTitle', 'shortTitle', 'productTitle', 'skuName', 'goodsName', 'goods_name']);
    const title = bestTitle(structured.name, embeddedTitle, selectors.title);
    const bodyText = document.body?.innerText?.slice(0, 200000) || '';
    const priceContextText = firstText([
      '[class*="Price--root"]', '[class*="Price--priceWrapper"]', '[class*="priceWrap"]',
      '[class*="price-panel"]', '.summary-price', '.tb-property-cont',
    ]);
    const pagePrice = firstNumber(firstText(selectors.price));
    const statePrice = embeddedNumber(source, ['priceText', 'salePrice', 'promotionPrice', 'jdPrice', 'minGroupPrice', 'minNormalPrice']);
    const effectivePrice = /^(?:淘宝|天猫)$/.test(platform())
      ? labeledNumber(priceContextText, ['券后', '到手价?', '折后', '活动价', '促销价'])
        || labeledNumber(bodyText, ['券后', '到手价?', '折后', '活动价', '促销价'])
      : 0;
    const originalPrice = labeledNumber(priceContextText, ['优惠前', '原价', '划线价'])
      || labeledNumber(bodyText, ['优惠前', '原价', '划线价']);
    const memberPriceText = firstText(['[class*=memberPrice]', '[class*=vipPrice]', '[class*=plus-price]', '[class*=Price][class*=member]']);
    const couponText = firstText(['[class*=coupon] [class*=price]', '[class*=Coupon] [class*=amount]', '.quan-item .text', '[class*=discountCoupon]']);
    const discountText = firstText(['[class*=promotion] [class*=price]', '[class*=Promotion] [class*=amount]', '.prom-item', '[class*=fullReduction]']);
    const imageValue = Array.isArray(structured.image) ? structured.image[0] : structured.image;
    const imageNode = selectors.image.map((selector) => document.querySelector(selector)).find(Boolean);
    const imageUrl = imageValue || imageNode?.getAttribute('content') || imageNode?.currentSrc || imageNode?.src || '';
    const price = effectivePrice || pagePrice || firstNumber(offers.price || offers.lowPrice || structured.price) || statePrice;
    const memberPrice = firstNumber(memberPriceText);
    const sku = clean(structured.sku || embeddedString(source, ['skuId', 'skuCode', 'goodsId', 'goods_id']) || identity());
    const specs = specifications();
    if (effectivePrice) specs['价格口径'] = '页面券后/到手价，已包含页面展示优惠';
    if (originalPrice > price) specs['优惠前价格'] = originalPrice;
    const includedDiscounts = effectivePrice > 0;
    const result = {
      title: title.slice(0, 200), category: 'unknown', platform: platform(), url: canonicalUrl(),
      brand: typeof structured.brand === 'object' ? clean(structured.brand?.name) : clean(structured.brand || embeddedString(source, ['brandName'])),
      model: clean(structured.model || structured.mpn || embeddedString(source, ['productModel', 'model'])),
      sku: sku.slice(0, 100), specs, price,
      coupon: includedDiscounts ? 0 : number(couponText), platform_discount: includedDiscounts ? 0 : number(discountText), member_discount: includedDiscounts ? 0 : memberPrice > 0 && price > memberPrice ? price - memberPrice : 0,
      subsidy: 0, pay_discount: 0, shipping: 0, gift_value: 0, condition: /二手|翻新|拆封/.test(bodyText) ? 'used_or_refurbished' : 'new',
      official_store: /官方旗舰|官方店|京东自营|品牌直营/.test(bodyText), return_days: 7,
      warranty_months: 12, store_name: storeName(offers.seller?.name || firstText(selectors.store)), image_url: String(imageUrl).slice(0, 1000),
      selected_variant: selectedVariant(), region: firstText(selectors.region) || 'unknown',
      membership: memberPriceText ? '页面显示会员条件' : 'unknown', observation_status: 'requires_confirmation',
      evidence: { type: 'browser_visible_page', url: canonicalUrl(), page_title: document.title, image_url: imageUrl, collector_version: '0.4.1', price_basis: effectivePrice ? 'visible_effective_price' : 'visible_page_price' },
      notes: `由 ValuSee 扩展读取当前可见页面；${effectivePrice ? '当前价格采用页面券后/到手价，不再重复扣减页面优惠；' : ''}发送前请确认 SKU、地区、会员资格、优惠和价格。`,
    };
    const missing = [];
    if (!result.title || /^(京东|淘宝网?|天猫|拼多多)(\s*[-_|·].*)?$/.test(result.title)) missing.push('商品标题');
    if (!result.price) missing.push('当前价格');
    if (!result.sku && !result.selected_variant) missing.push('SKU/已选规格');
    return { product: result, diagnostics: { missing, platform: result.platform } };
  };

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === 'VALUSee_PING_V4' || message?.type === 'VALUSee_PING_V3' || message?.type === 'VALUSee_PING_V2') sendResponse({ ok: true, version: '0.4.1' });
    if (message?.type === 'VALUSee_COLLECT_PRODUCT_V4' || message?.type === 'VALUSee_COLLECT_PRODUCT_V3' || message?.type === 'VALUSee_COLLECT_PRODUCT_V2') {
      try { sendResponse({ ok: true, ...collect() }); }
      catch (error) { sendResponse({ ok: false, error: `页面读取失败：${error.message}` }); }
    }
  });
})();
