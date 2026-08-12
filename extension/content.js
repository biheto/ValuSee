(() => {
  if (window.__VALUSeeCollectorV6) return;
  window.__VALUSeeCollectorV6 = true;

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
      if (/用户评价|商品评价|宝贝评价|累计评价|全部评价|已售\s*\d|月销|多人评价|加购|购物车|收藏夹|免费开店|帮助中心|搜索本店|搜索$|网页无障碍|商品详情|规格参数|售后保障/i.test(value)) return;
      if (/^(?:淘宝网?|天猫|京东|拼多多|商品详情|店铺首页)$/i.test(value)) return;
      let finalScore = score + Math.min(value.length, 100) / 12;
      if (node?.matches?.('h1,h2')) finalScore += 20;
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
    (document.body?.innerText || '').split(/\r?\n/).slice(0, 180).forEach((line) => add(line, 9));
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
  const labeledRange = (value, labels) => {
    const normalized = clean(value).replace(/,/g, '');
    for (const label of labels) {
      const match = normalized.match(new RegExp(`(?:${label})\\s*(?:约|低至)?\\s*[¥￥]?\\s*(\\d+(?:\\.\\d{1,2})?)\\s*(?:-|~|～|至)\\s*[¥￥]?\\s*(\\d+(?:\\.\\d{1,2})?)`, 'i'));
      if (match) return [Number(match[1]), Number(match[2])].sort((left, right) => left - right);
    }
    return [];
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
      title: ['.sku-name', '#name h1', '[class*="sku-name" i]', '[class*="product-title" i]', ...common.title],
      price: ['.summary-price .p-price .price', '.p-price .price', '[class*="price-now" i]', '[class*="jd-price" i]', '[class*="price"] [class*="num"]', ...common.price],
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
      title: ['[class*="goodsName" i]', '[class*="goods-name" i]', '[class*="goods-title" i]', '[class*="product-title" i]', 'main h1', 'main h2', 'h2', ...common.title],
      price: ['[class*="wholesalePrice" i]', '[class*="priceRange" i]', '[class*="groupPrice" i]', '[class*="salePrice" i]', '[class*="goodsPrice" i]', '[class*="price" i] [class*="price" i]', ...common.price],
      store: ['[class*="shopInfo" i] [class*="name" i]', '[class*="merchant" i] [class*="name" i]', '[class*="mallName" i]', '[class*="shop-name" i]', ...common.store],
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
      if (normalized && normalized.length <= 80 && !/^(?:颜色分类|尺码|规格|商品详情|规格参数|售后保障|评价|全部)$/.test(normalized) && !/商品详情|规格参数|售后保障|用户评价/.test(normalized) && !values.includes(normalized)) values.push(normalized);
    });
    return values.slice(0, 8).join(' / ');
  };
  const storeName = (value) => clean(value)
    .split(/(?:·|\||丨)?\s*\d+(?:\.\d+)?\s*VIP|好评率|平均\s*\d|客服满意度|粉丝\s*\d/i)[0]
    .replace(/\s*(?:客服|进店)\s*$/g, '')
    .trim()
    .slice(0, 100);
  const storeFromBody = () => {
    const lines = (document.body?.innerText || '').split(/\r?\n/).map(clean).filter(Boolean);
    const labelIndex = lines.findIndex((line) => /^店铺信息$/.test(line));
    if (labelIndex >= 0) {
      const candidate = lines.slice(labelIndex + 1, labelIndex + 5).find((line) => !/联系客?服|进店|查看|全部商品/.test(line));
      if (candidate) return candidate.replace(/[>›].*$/, '');
    }
    const inline = clean(document.body?.innerText || '').match(/店铺信息\s*([^\n]{2,80}?)(?:联系客?服|进店|$)/);
    return inline?.[1] || '';
  };
  const wholesaleOptions = (value) => {
    const options = [];
    for (const match of value.matchAll(/([^\s¥￥]{0,24}[（(]\s*\d+\s*个装\s*[）)])/g)) {
      const option = clean(match[1]);
      if (option && !options.includes(option)) options.push(option);
    }
    return options.slice(0, 12);
  };
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
    const allowed = new Set(['id', 'item_id', 'sku', 'skuid', 'goods_id', 'goodsid', 'gid']);
    [...url.searchParams.keys()].forEach((key) => { if (!allowed.has(key.toLowerCase())) url.searchParams.delete(key); });
    url.hash = '';
    return url.toString();
  };
  const identity = () => {
    const params = new URL(location.href).searchParams;
    const queryId = params.get('skuId') || params.get('sku') || params.get('id') || params.get('item_id') || params.get('goods_id') || params.get('goodsId') || params.get('gid');
    if (queryId) return queryId;
    if (platform() === '京东') return location.pathname.match(/\/(\d{5,})(?:\.html)?/)?.[1] || '';
    if (platform() === '拼多多') return location.pathname.match(/\/(?:goods|detail)\/(\d{5,})/)?.[1] || '';
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
    const wholesaleRange = platform() === '拼多多' ? labeledRange(bodyText, ['批发价']) : [];
    const wholesalePrice = wholesaleRange[0] || 0;
    const originalPrice = labeledNumber(priceContextText, ['优惠前', '原价', '划线价'])
      || labeledNumber(bodyText, ['优惠前', '原价', '划线价']);
    const originalRange = platform() === '拼多多' ? labeledRange(bodyText, ['原价']) : [];
    const memberPriceText = firstText(['[class*=memberPrice]', '[class*=vipPrice]', '[class*=plus-price]', '[class*=Price][class*=member]']);
    const couponText = firstText(['[class*=coupon] [class*=price]', '[class*=Coupon] [class*=amount]', '.quan-item .text', '[class*=discountCoupon]']);
    const discountText = firstText(['[class*=promotion] [class*=price]', '[class*=Promotion] [class*=amount]', '.prom-item', '[class*=fullReduction]']);
    const imageValue = Array.isArray(structured.image) ? structured.image[0] : structured.image;
    const imageNode = selectors.image.map((selector) => document.querySelector(selector)).find(Boolean);
    const imageUrl = imageValue || imageNode?.getAttribute('content') || imageNode?.currentSrc || imageNode?.src || '';
    const jdPrice = platform() === '京东'
      ? labeledNumber(bodyText, ['到手价', '促销价', '京东价', '售价', '会员价']) || statePrice
      : 0;
    const price = effectivePrice || wholesalePrice || jdPrice || pagePrice || firstNumber(offers.price || offers.lowPrice || structured.price) || statePrice;
    const memberPrice = firstNumber(memberPriceText);
    const pageIdentity = identity();
    const sku = clean(platform() === '京东' && pageIdentity ? pageIdentity : structured.sku || embeddedString(source, ['skuId', 'skuCode', 'goodsId', 'goods_id']) || pageIdentity);
    const specs = specifications();
    if (effectivePrice) specs['价格口径'] = '页面券后/到手价，已包含页面展示优惠';
    if (wholesaleRange.length) {
      specs['价格口径'] = '页面批发价区间最低价，最终价格取决于包装规格与数量';
      specs['批发价区间'] = `¥${wholesaleRange[0]} - ¥${wholesaleRange[1]}`;
    }
    if (originalRange.length) specs['原价区间'] = `¥${originalRange[0]} - ¥${originalRange[1]}`;
    const minimumOrder = labeledNumber(bodyText, ['起批量']);
    if (minimumOrder) specs['起批量'] = `${minimumOrder}件`;
    const availableOptions = wholesaleOptions(bodyText);
    if (availableOptions.length) specs['可选包装'] = availableOptions.join(' / ');
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
      warranty_months: 12, store_name: storeName(offers.seller?.name || embeddedString(source, ['mallName', 'shopName', 'storeName', 'merchantName']) || firstText(selectors.store) || storeFromBody()), image_url: String(imageUrl).slice(0, 1000),
      selected_variant: selectedVariant(), region: firstText(selectors.region) || 'unknown',
      membership: memberPriceText ? '页面显示会员条件' : 'unknown', observation_status: 'requires_confirmation',
      evidence: { type: 'browser_visible_page', url: canonicalUrl(), page_title: document.title, image_url: imageUrl, collector_version: '0.4.3', price_basis: effectivePrice ? 'visible_effective_price' : wholesalePrice ? 'visible_wholesale_minimum' : 'visible_page_price' },
      notes: `由 ValuSee 扩展读取当前可见页面；${effectivePrice ? '当前价格采用页面券后/到手价，不再重复扣减页面优惠；' : ''}${wholesalePrice ? '当前价格采用批发区间最低价，最终价格须按包装规格和采购数量确认；' : ''}发送前请确认 SKU、地区、会员资格、优惠和价格。`,
    };
    const missing = [];
    if (!result.title || /^(京东|淘宝网?|天猫|拼多多)(\s*[-_|·].*)?$/.test(result.title)) missing.push('商品标题');
    if (!result.price) missing.push('当前价格');
    if (!result.sku && !result.selected_variant) missing.push('SKU/已选规格');
    return { product: result, diagnostics: { missing, platform: result.platform } };
  };

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === 'VALUSee_PING_V6' || message?.type === 'VALUSee_PING_V5' || message?.type === 'VALUSee_PING_V4' || message?.type === 'VALUSee_PING_V3' || message?.type === 'VALUSee_PING_V2') sendResponse({ ok: true, version: '0.4.3' });
    if (message?.type === 'VALUSee_COLLECT_PRODUCT_V6' || message?.type === 'VALUSee_COLLECT_PRODUCT_V5' || message?.type === 'VALUSee_COLLECT_PRODUCT_V4' || message?.type === 'VALUSee_COLLECT_PRODUCT_V3' || message?.type === 'VALUSee_COLLECT_PRODUCT_V2') {
      try { sendResponse({ ok: true, ...collect() }); }
      catch (error) { sendResponse({ ok: false, error: `页面读取失败：${error.message}` }); }
    }
  });
})();
