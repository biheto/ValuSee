let product = null;
let config = { appUrl: 'https://valusee.com', accessToken: '' };
const byId = (id) => document.getElementById(id);
const fields = ['title', 'price', 'sku', 'variant', 'coupon', 'discount', 'memberDiscount', 'shipping', 'region', 'membership'];

document.addEventListener('DOMContentLoaded', async () => {
  config = await chrome.storage.local.get(config);
  byId('appUrl').value = config.appUrl;
  updateConnection();
  collectCurrentPage();
});

byId('settings').addEventListener('click', () => { byId('settingsPanel').hidden = !byId('settingsPanel').hidden; });
byId('connect').addEventListener('click', connect);
byId('disconnect').addEventListener('click', async () => {
  config.accessToken = '';
  await chrome.storage.local.set({ accessToken: '' });
  updateConnection();
});
byId('capture').addEventListener('click', sendCapture);
byId('open').addEventListener('click', () => chrome.runtime.sendMessage({ type: 'VALUSee_OPEN_APP' }));

async function connect() {
  const appUrl = normalizedAppUrl(byId('appUrl').value);
  const email = byId('email').value.trim();
  const password = byId('password').value;
  setStatus('正在连接...');
  try {
    const response = await fetch(`${appUrl}/api/v1/auth/login`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password })
    });
    if (!response.ok) throw new Error(await responseMessage(response));
    const data = await response.json();
    config = { appUrl, accessToken: data.access_token };
    await chrome.storage.local.set(config);
    byId('password').value = '';
    byId('settingsPanel').hidden = true;
    updateConnection();
    setStatus('账户连接成功。');
  } catch (error) { setStatus(`连接失败：${error.message}`, true); }
}

function collectCurrentPage() {
  chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
    if (!tab?.id) return;
    chrome.tabs.sendMessage(tab.id, { type: 'VALUSee_COLLECT_PRODUCT' }, (response) => {
      if (chrome.runtime.lastError || !response?.ok) {
        byId('preview').textContent = '请在淘宝、天猫、京东或拼多多商品详情页使用扩展。'; return;
      }
      product = response.product;
      byId('title').value = product.title || '';
      byId('price').value = product.price || '';
      byId('sku').value = product.sku || '';
      byId('variant').value = product.selected_variant || '';
      byId('coupon').value = product.coupon || '';
      byId('discount').value = product.platform_discount || '';
      byId('memberDiscount').value = product.member_discount || '';
      byId('shipping').value = product.shipping || '';
      byId('region').value = product.region === 'unknown' ? '' : product.region || '';
      byId('membership').value = product.membership || '';
      byId('source').textContent = `${product.platform} · ${product.store_name || '店铺待确认'} · ${new Date().toLocaleString('zh-CN')}`;
      byId('editor').hidden = false;
      byId('preview').hidden = true;
    });
  });
}

async function sendCapture() {
  if (!product) return;
  const isLocal = /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(config.appUrl);
  if (!config.accessToken && !isLocal) {
    byId('settingsPanel').hidden = false;
    setStatus('请先登录 ValuSee 账户。', true);
    return;
  }
  product = {
    ...product, title: byId('title').value.trim(), price: numeric('price'), sku: byId('sku').value.trim(),
    selected_variant: byId('variant').value.trim(), coupon: numeric('coupon'),
    platform_discount: numeric('discount'), member_discount: numeric('memberDiscount'), shipping: numeric('shipping'),
    region: byId('region').value.trim() || 'unknown', membership: byId('membership').value.trim() || 'unknown',
    observation_status: 'requires_confirmation',
    evidence: { ...product.evidence, captured_at: new Date().toISOString(), user_reviewed_in_extension: true }
  };
  if (!product.title || !product.url) return setStatus('商品标题和链接不能为空。', true);
  byId('capture').disabled = true;
  setStatus('正在发送...');
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (config.accessToken) headers.Authorization = `Bearer ${config.accessToken}`;
    const response = await fetch(`${config.appUrl}/api/v1/shopping/extension/captures`, {
      method: 'POST', headers, body: JSON.stringify({ product, source: 'browser_extension_visible_page', captured_at: new Date().toISOString() })
    });
    if (response.status === 401) {
      config.accessToken = '';
      await chrome.storage.local.set({ accessToken: '' });
      updateConnection();
    }
    if (!response.ok) throw new Error(await responseMessage(response));
    setStatus('已发送。请在 ValuSee 收件箱完成最终确认。');
  } catch (error) {
    setStatus(`发送失败：${error.message}`, true);
    byId('capture').disabled = false;
  }
}

function updateConnection() {
  byId('connection').textContent = config.accessToken ? '账户已连接' : '尚未连接账户';
  byId('connection').className = config.accessToken ? 'connected' : '';
}
function normalizedAppUrl(value) {
  const parsed = new URL(value.trim());
  const local = ['127.0.0.1', 'localhost'].includes(parsed.hostname);
  if (parsed.protocol !== 'https:' && !(local && parsed.protocol === 'http:')) throw new Error('线上地址必须使用 HTTPS');
  return parsed.origin;
}
function numeric(id) { return Math.max(0, Number(byId(id).value || 0)); }
function setStatus(value, error = false) { byId('status').textContent = value; byId('status').className = error ? 'error' : ''; }
async function responseMessage(response) { try { const data = await response.json(); return data.detail || `HTTP ${response.status}`; } catch { return `HTTP ${response.status}`; } }
