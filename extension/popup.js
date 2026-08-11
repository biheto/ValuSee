let product = null;
let config = { appUrl: 'https://valusee.com', apiUrl: '', accessToken: '', accountEmail: '' };
const byId = (id) => document.getElementById(id);
const supportedHosts = ['jd.com', 'taobao.com', 'tmall.com', 'pinduoduo.com', 'yangkeduo.com'];

document.addEventListener('DOMContentLoaded', async () => {
  config = await chrome.storage.local.get(config);
  byId('appUrl').value = config.appUrl;
  byId('email').value = config.accountEmail || '';
  bindEvents();
  await validateSession();
  await collectCurrentPage();
});

function bindEvents() {
  byId('settings').addEventListener('click', () => { byId('settingsPanel').hidden = !byId('settingsPanel').hidden; });
  byId('connect').addEventListener('click', connect);
  byId('disconnect').addEventListener('click', disconnect);
  byId('capture').addEventListener('click', sendCapture);
  byId('retry').addEventListener('click', collectCurrentPage);
  byId('open').addEventListener('click', () => chrome.runtime.sendMessage({ type: 'VALUSee_OPEN_APP' }));
}

async function connect() {
  let appUrl;
  try { appUrl = normalizedAppUrl(byId('appUrl').value); } catch (error) { return setStatus(error.message, true); }
  const email = byId('email').value.trim();
  const password = byId('password').value;
  const mfaCode = byId('mfaCode').value.trim();
  if (!email || !password) return setStatus('请输入登录邮箱和密码。', true);
  setBusy('connect', true);
  setStatus('正在验证账户...');
  try {
    const { response, baseUrl } = await fetchApi('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, mfa_code: mfaCode }),
    }, appUrl, '');
    if (!response.ok) throw new Error(await responseMessage(response));
    const data = await response.json();
    config = { appUrl, apiUrl: baseUrl, accessToken: data.access_token, accountEmail: data.user?.email || email };
    await chrome.storage.local.set(config);
    byId('password').value = '';
    byId('mfaCode').value = '';
    byId('settingsPanel').hidden = true;
    updateConnection(true);
    setStatus(`已连接 ${config.accountEmail}。`);
  } catch (error) {
    await clearSession();
    byId('settingsPanel').hidden = false;
    setStatus(`连接失败：${error.message}`, true);
  } finally { setBusy('connect', false); }
}

async function disconnect() {
  await clearSession();
  byId('settingsPanel').hidden = false;
  setStatus('已断开账户连接。');
}

async function validateSession() {
  if (!config.accessToken) {
    updateConnection(false);
    return false;
  }
  updateConnection(null);
  try {
    const { response, baseUrl } = await fetchApi('/api/v1/auth/me', {
      headers: { Authorization: `Bearer ${config.accessToken}` },
    });
    if (!response.ok) {
      if (response.status === 401) await clearSession();
      else throw new Error(await responseMessage(response));
      return false;
    }
    const data = await response.json();
    config.apiUrl = baseUrl;
    config.accountEmail = data.user?.email || config.accountEmail;
    await chrome.storage.local.set({ apiUrl: config.apiUrl, accountEmail: config.accountEmail });
    updateConnection(true);
    return true;
  } catch (error) {
    updateConnection(null);
    setStatus(`账户状态暂时无法验证：${error.message}`, true);
    return false;
  }
}

async function collectCurrentPage() {
  product = null;
  byId('editor').hidden = true;
  byId('preview').hidden = false;
  byId('preview').textContent = '正在读取当前商品页...';
  setBusy('retry', true);
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !isSupportedUrl(tab.url || '')) throw new Error('请打开京东、淘宝、天猫或拼多多商品详情页。');
    let ready = await sendTabMessage(tab.id, { type: 'VALUSee_PING_V2' });
    if (!ready?.ok) {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content.js'] });
    }
    const response = await sendTabMessage(tab.id, { type: 'VALUSee_COLLECT_PRODUCT_V2' });
    if (!response?.ok || !response.product) throw new Error(response?.error || '页面采集脚本未响应，请刷新商品页后重试。');
    product = response.product;
    fillEditor(product);
    byId('editor').hidden = false;
    byId('preview').hidden = true;
    const missing = response.diagnostics?.missing || [];
    if (missing.length) setStatus(`已读取页面，但${missing.join('、')}未识别，请补充后发送。`, true);
    else setStatus('商品信息已识别，请核对当前规格、价格和优惠。');
  } catch (error) {
    byId('preview').textContent = error.message;
    setStatus('可刷新商品页后重试；若平台隐藏字段，也可在 ValuSee 上传截图。', true);
  } finally { setBusy('retry', false); }
}

function fillEditor(value) {
  byId('title').value = value.title || '';
  byId('price').value = value.price || '';
  byId('sku').value = value.sku || '';
  byId('variant').value = value.selected_variant || '';
  byId('coupon').value = value.coupon || '';
  byId('discount').value = value.platform_discount || '';
  byId('memberDiscount').value = value.member_discount || '';
  byId('shipping').value = value.shipping || '';
  byId('region').value = value.region === 'unknown' ? '' : value.region || '';
  byId('membership').value = value.membership === 'unknown' ? '' : value.membership || '';
  byId('source').textContent = `${value.platform} · ${value.store_name || '店铺待确认'} · ${new Date().toLocaleString('zh-CN')}`;
}

async function sendCapture() {
  if (!product) return setStatus('请先识别当前商品页。', true);
  if (!config.accessToken && !isLocalApp(config.appUrl)) {
    byId('settingsPanel').hidden = false;
    setStatus('请先连接 ValuSee 账户。', true);
    return;
  }
  product = {
    ...product,
    title: byId('title').value.trim(), price: numeric('price'), sku: byId('sku').value.trim(),
    selected_variant: byId('variant').value.trim(), coupon: numeric('coupon'),
    platform_discount: numeric('discount'), member_discount: numeric('memberDiscount'), shipping: numeric('shipping'),
    region: byId('region').value.trim() || 'unknown', membership: byId('membership').value.trim() || 'unknown',
    observation_status: 'requires_confirmation',
    evidence: { ...product.evidence, captured_at: new Date().toISOString(), user_reviewed_in_extension: true },
  };
  if (!product.title || !product.url) return setStatus('商品标题和链接不能为空。', true);
  setBusy('capture', true);
  setStatus('正在发送...');
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (config.accessToken) headers.Authorization = `Bearer ${config.accessToken}`;
    const { response, baseUrl } = await fetchApi('/api/v1/shopping/extension/captures', {
      method: 'POST', headers, body: JSON.stringify({ product, source: 'browser_extension_visible_page', captured_at: new Date().toISOString() }),
    });
    config.apiUrl = baseUrl;
    await chrome.storage.local.set({ apiUrl: baseUrl });
    if (response.status === 401) {
      const message = await responseMessage(response);
      await clearSession();
      byId('settingsPanel').hidden = false;
      throw new Error(`会话已过期，请重新登录（${message}）`);
    }
    if (!response.ok) throw new Error(await responseMessage(response));
    setStatus('已发送到 ValuSee，请在采集收件箱完成最终确认。');
  } catch (error) { setStatus(`发送失败：${error.message}`, true); }
  finally { setBusy('capture', false); }
}

function sendTabMessage(tabId, message) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) resolve(null);
      else resolve(response || null);
    });
  });
}

function isSupportedUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && supportedHosts.some((host) => url.hostname === host || url.hostname.endsWith(`.${host}`));
  } catch { return false; }
}

function apiCandidatesFor(appUrl, preferred = config.apiUrl) {
  const origin = normalizedAppUrl(appUrl);
  const host = new URL(origin).hostname.toLowerCase();
  const values = host === 'valusee.com' || host === 'www.valusee.com' ? [preferred, 'https://api.valusee.com', origin] : [preferred, origin];
  return values.filter((value, index) => value && values.indexOf(value) === index);
}

async function fetchApi(path, options, appUrl = config.appUrl, preferred = config.apiUrl) {
  let lastError;
  const candidates = apiCandidatesFor(appUrl, preferred);
  for (const [index, baseUrl] of candidates.entries()) {
    try {
      const response = await fetch(`${baseUrl}${path}`, options);
      if (response.status < 500 || index === candidates.length - 1) return { response, baseUrl };
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) { lastError = error; }
  }
  throw lastError || new Error('ValuSee API 暂时无法连接');
}

function normalizedAppUrl(value) {
  const parsed = new URL(String(value || '').trim());
  const local = ['127.0.0.1', 'localhost'].includes(parsed.hostname);
  if (parsed.protocol !== 'https:' && !(local && parsed.protocol === 'http:')) throw new Error('线上地址必须使用 HTTPS');
  return parsed.origin;
}

function isLocalApp(value) {
  try { return ['127.0.0.1', 'localhost'].includes(new URL(value).hostname); } catch { return false; }
}
function numeric(id) { return Math.max(0, Number(byId(id).value || 0)); }
function setStatus(value, error = false) { byId('status').textContent = value; byId('status').className = error ? 'error' : ''; }
function setBusy(id, busy) { byId(id).disabled = busy; }
function updateConnection(valid) {
  const label = valid === true ? `已连接${config.accountEmail ? ` · ${config.accountEmail}` : ''}` : valid === false ? '尚未连接账户' : '正在验证账户';
  byId('connection').textContent = label;
  byId('connection').className = valid === true ? 'connected' : '';
}
async function clearSession() {
  config.accessToken = '';
  await chrome.storage.local.set({ accessToken: '' });
  updateConnection(false);
}
async function responseMessage(response) {
  try { const data = await response.json(); return data.detail || `HTTP ${response.status}`; }
  catch { return `HTTP ${response.status}`; }
}
