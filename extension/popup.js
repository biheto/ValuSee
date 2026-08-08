let product = null;
const preview = document.querySelector('#preview');
const capture = document.querySelector('#capture');
const status = document.querySelector('#status');

chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
  if (!tab?.id) return;
  chrome.tabs.sendMessage(tab.id, { type: 'VALUSee_COLLECT_PRODUCT' }, (response) => {
    if (chrome.runtime.lastError || !response?.ok) {
      preview.textContent = '请在淘宝、天猫、京东或拼多多商品详情页使用扩展。'; return;
    }
    product = response.product;
    preview.innerHTML = `<strong>${escapeHtml(product.title)}</strong><span>${escapeHtml(product.platform)} · ${product.price ? `¥${product.price}` : '价格待确认'}</span>`;
    capture.disabled = false;
  });
});
capture.addEventListener('click', async () => {
  capture.disabled = true; status.textContent = '正在发送...';
  try {
    const response = await fetch('http://127.0.0.1:8200/api/v1/shopping/extension/captures', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: 'local-user', product, source: 'browser_extension', captured_at: new Date().toISOString() }) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    status.textContent = '已加入 ValuSee，打开网站确认商品信息。';
  } catch (error) { status.textContent = `发送失败：${error.message}`; capture.disabled = false; }
});
document.querySelector('#open').addEventListener('click', () => chrome.runtime.sendMessage({ type: 'VALUSee_OPEN_APP' }));
function escapeHtml(value) { const node = document.createElement('span'); node.textContent = String(value || ''); return node.innerHTML; }
