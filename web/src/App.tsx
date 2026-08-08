import {
  Bell,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Clock3,
  FileText,
  History,
  Link2,
  Loader2,
  Plus,
  Receipt,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';

type Product = {
  title: string; platform: string; url: string; brand: string; model: string; sku: string;
  specs: Record<string, string>; price: number; coupon: number; platform_discount: number;
  member_discount: number; subsidy: number; pay_discount: number; shipping: number; gift_value: number;
  condition: string; official_store: boolean; return_days: number; warranty_months: number; notes: string;
};
type Decision = { task_id: string; status: string; result: {
  best_index: number | null; recommendation: string; recommendation_reason: string; summary: string;
  comparison_rows: Array<{ index: number; title: string; platform: string; model: string; same_item_relation: string; same_item_confidence: number; final_price: number; value_score: number; risk_level: string; suitable_for_user: boolean }>;
  price_breakdowns: Array<{ final_price: number }>;
  risk_reports: Array<{ overall_risk: string; reasons: string[] }>;
  report_markdown: string;
}};
type Monitor = { monitor_id: string; status: string; target_price: number; current_final_price: number; product: Product; expires_at: string; last_message: string };
type Purchase = { purchase_id: string; product: Product; paid_price: number; platform: string; store_name: string; purchased_at: string; price_protection_deadline?: string; return_deadline?: string; warranty_deadline?: string; status: string; reminders: Array<{ kind: string; deadline: string; label: string }>; notes: string };
type Capture = { capture_id: string; status: string; product: Product; source: string; captured_at: string };
type View = 'analyze' | 'monitors' | 'purchases' | 'history';

const sample: Product[] = [
  { title: 'AirPods Pro 2 USB-C 官方旗舰店', platform: '京东', url: 'https://example.com/jd-airpods', brand: 'Apple', model: 'AirPods Pro 2', sku: 'APP2-USBC', specs: { 接口: 'USB-C', 代次: '第二代' }, price: 1799, coupon: 140, platform_discount: 60, member_discount: 0, subsidy: 0, pay_discount: 20, shipping: 0, gift_value: 0, condition: '新品', official_store: true, return_days: 7, warranty_months: 12, notes: '官方店铺，适合 iPhone 用户。' },
  { title: 'AirPods Pro 2 Lightning 现货', platform: '拼多多', url: 'https://example.com/pdd-airpods', brand: 'Apple', model: 'AirPods Pro 2', sku: 'APP2-LIGHT', specs: { 接口: 'Lightning', 代次: '第二代' }, price: 1488, coupon: 80, platform_discount: 30, member_discount: 0, subsidy: 0, pay_discount: 0, shipping: 0, gift_value: 0, condition: '新品', official_store: false, return_days: 7, warranty_months: 12, notes: '价格更低，但接口和店铺资质需要确认。' },
];
const blank = (): Product => ({ title: '新商品候选', platform: '', url: '', brand: '', model: '', sku: '', specs: {}, price: 0, coupon: 0, platform_discount: 0, member_discount: 0, subsidy: 0, pay_discount: 0, shipping: 0, gift_value: 0, condition: '新品', official_store: false, return_days: 7, warranty_months: 12, notes: '' });

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(String(body.detail ?? `请求失败（${response.status}）`)); }
  return response.json();
}
const money = (value: number) => `¥${Number(value || 0).toFixed(0)}`;
const date = (value?: string) => value ? new Date(value).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) : '未设置';
const riskLabel: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险' };

export function App() {
  const [view, setView] = useState<View>('analyze');
  const [goal, setGoal] = useState('想买一副适合 iPhone 的降噪耳机，预算 1800 元以内');
  const [budget, setBudget] = useState(1800);
  const [products, setProducts] = useState<Product[]>(sample);
  const [result, setResult] = useState<Decision | null>(null);
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [purchases, setPurchases] = useState<Purchase[]>([]);
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [monitorProduct, setMonitorProduct] = useState(0);
  const [targetPrice, setTargetPrice] = useState(1300);
  const [purchaseProduct, setPurchaseProduct] = useState(0);
  const [paidPrice, setPaidPrice] = useState(0);

  const refreshRecords = async () => {
    try { const [m, p, c] = await Promise.all([request<Monitor[]>('/api/v1/shopping/monitors?user_id=local-user'), request<Purchase[]>('/api/v1/shopping/purchases?user_id=local-user'), request<Capture[]>('/api/v1/shopping/extension/captures?user_id=local-user')]); setMonitors(m); setPurchases(p); setCaptures(c.filter((item) => item.status === 'pending_confirmation')); } catch { /* backend may be offline while the static preview is open */ }
  };
  useEffect(() => { void refreshRecords(); }, []);
  useEffect(() => {
    const saved = localStorage.getItem('valuesee-last-report');
    if (saved) {
      try { setResult(JSON.parse(saved) as Decision); } catch { localStorage.removeItem('valuesee-last-report'); }
    }
  }, []);

  async function runDecision(event?: FormEvent) {
    event?.preventDefault(); setLoading(true); setError('');
    try { const data = await request<Decision>('/api/v1/shopping/decide', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ goal, products, profile: { budget, use_case: goal, devices: ['iPhone', 'MacBook Pro'], brand_preferences: ['Apple'], sensitivities: ['售后', '接口兼容', '保修'], acceptable_risk: 'medium' }, require_human_review: false }) }); setResult(data); setMessage('分析完成，报告已生成。'); localStorage.setItem('valuesee-last-report', JSON.stringify(data)); } catch (err) { setError(err instanceof Error ? err.message : '分析失败'); } finally { setLoading(false); }
  }
  async function addUrl(event: FormEvent) {
    event.preventDefault(); if (!url.trim()) return; setError('');
    try { const data = await request<{ product: Product; message: string }>('/api/v1/shopping/parse-url', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) }); setProducts((items) => [...items, data.product]); setUrl(''); setMessage(data.message); } catch (err) { setError(err instanceof Error ? err.message : '链接读取失败'); }
  }
  async function addImage(file: File) {
    const form = new FormData(); form.append('file', file); setLoading(true); setError('');
    try { const data = await request<{ product: Product; warning: string; ocr_provider: string; requires_confirmation: boolean }>('/api/v1/shopping/parse-image', { method: 'POST', body: form }); setProducts((items) => [...items, data.product]); setMessage(data.warning || `截图识别完成（${data.ocr_provider}），请确认商品信息。`); } catch (err) { setError(err instanceof Error ? err.message : '截图识别失败'); } finally { setLoading(false); }
  }
  async function importCapture(capture: Capture) {
    try { await request(`/api/v1/shopping/extension/captures/${capture.capture_id}/confirm`, { method: 'POST' }); setProducts((items) => [...items, capture.product]); setCaptures((items) => items.filter((item) => item.capture_id !== capture.capture_id)); setMessage('已将浏览器采集商品加入候选清单，请确认字段。'); } catch (err) { setError(err instanceof Error ? err.message : '导入采集商品失败'); }
  }
  function updateProduct(index: number, patch: Partial<Product>) { setProducts((items) => items.map((item, i) => i === index ? { ...item, ...patch } : item)); }
  async function createMonitor(event: FormEvent) { event.preventDefault(); const product = products[monitorProduct]; try { await request<Monitor>('/api/v1/shopping/monitors', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ product, target_price: targetPrice, monitor_days: 30, notify_channel: 'in_app' }) }); setMessage('降价监控已创建，服务重启后仍会保留。'); await refreshRecords(); } catch (err) { setError(err instanceof Error ? err.message : '创建监控失败'); } }
  async function createPurchase(event: FormEvent) { event.preventDefault(); const product = products[purchaseProduct]; try { await request<Purchase>('/api/v1/shopping/purchases', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ product, paid_price: paidPrice || product.price, platform: product.platform, store_name: product.official_store ? '官方/自营店' : '待确认', price_protection_days: 7, return_days: product.return_days, warranty_months: product.warranty_months, notes: '由 ValuSee 记录，提醒仅供参考。' }) }); setMessage('购买记录已保存，保价和退货提醒已建立。'); await refreshRecords(); } catch (err) { setError(err instanceof Error ? err.message : '保存购买记录失败'); } }

  const best = useMemo(() => result?.result.best_index == null ? null : result.result.comparison_rows[result.result.best_index], [result]);
  const nav: Array<[View, string, typeof Search]> = [['analyze', '分析商品', Search], ['monitors', '降价监控', Bell], ['purchases', '我的购买', Receipt], ['history', '历史报告', History]];
  return <main className="valuesee-app">
    <header className="app-header"><div className="brand-lockup"><img className="brand-logo" src="/brand/logo-icon.png" alt="ValuSee" /><div><strong>ValuSee</strong><span>买之前，先看清价值</span></div></div><nav>{nav.map(([key, label, Icon]) => <button className={view === key ? 'active' : ''} key={key} onClick={() => setView(key)}><Icon size={17} />{label}</button>)}</nav><button className="profile-button">本地账户</button></header>
    {message && <div className="toast"><CheckCircle2 size={16} />{message}<button onClick={() => setMessage('')}>关闭</button></div>}
    {error && <div className="error-banner">{error}</div>}
    {view === 'analyze' && <>
      <section className="hero"><div className="hero-copy"><div className="eyebrow"><Sparkles size={16} />AI 购物决策助手</div><h1>别只看便不便宜，先看它值不值得。</h1><p>识别真假同款，算清真实到手价，结合你的预算和设备给出建议。买完之后，继续帮你盯住降价与保价。</p><form className="decision-box" onSubmit={runDecision}><textarea value={goal} onChange={(e) => setGoal(e.target.value)} /><div className="decision-controls"><label>预算 <input type="number" min={0} value={budget} onChange={(e) => setBudget(Number(e.target.value))} /> 元</label><button type="submit" disabled={loading}>{loading ? <Loader2 className="spin" size={18} /> : <Search size={18} />}立即分析</button></div></form></div><div className="hero-aside"><div className="hero-visual"><img src="/brand/xiaozhi.png" alt="小值 ValuSee 角色" /><div className="visual-badge">看清价值，再决定</div></div></div></section>
      <section className="quick-strip"><button onClick={() => setGoal('帮我选一台适合代码办公的 27 英寸显示器，预算 2500 元')}><Search size={20} /><strong>帮我选</strong><span>输入需求，得到适配候选</span><ChevronRight size={17} /></button><button onClick={() => document.getElementById('products')?.scrollIntoView({ behavior: 'smooth' })}><Link2 size={20} /><strong>帮我比</strong><span>添加链接，识别是否同款</span><ChevronRight size={17} /></button><button onClick={() => setView('monitors')}><Clock3 size={20} /><strong>等等再买</strong><span>到目标价再提醒我</span><ChevronRight size={17} /></button></section>
      {captures.length > 0 && <section className="capture-inbox"><div><strong>浏览器采集收件箱</strong><span>这些商品来自你正在浏览的页面，确认后才会加入分析。</span></div><div className="capture-items">{captures.map((capture) => <article key={capture.capture_id}><div><b>{capture.product.title}</b><small>{capture.product.platform} · {capture.product.price ? money(capture.product.price) : '价格待确认'}</small></div><button onClick={() => void importCapture(capture)}>加入候选</button></article>)}</div></section>}
      <section className="workspace-grid" id="products"><div className="panel"><div className="section-heading"><div><span>第一步</span><h2>添加要比较的商品</h2></div><button className="soft-button" onClick={() => setProducts((items) => [...items, blank()])}><Plus size={17} />手动添加</button></div><form className="url-form" onSubmit={addUrl}><Link2 size={18} /><input placeholder="粘贴淘宝、京东、拼多多商品链接" value={url} onChange={(e) => setUrl(e.target.value)} /><button>读取链接</button><label className="upload-button"><Upload size={16} />识别截图<input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => e.target.files?.[0] && void addImage(e.target.files[0])} /></label></form><div className="product-list">{products.map((product, index) => <article className="product-editor" key={`${index}-${product.title}`}><div className="product-editor-head"><span>候选 {index + 1}</span><button className="icon-button" title="删除候选" onClick={() => setProducts((items) => items.filter((_, i) => i !== index))} disabled={products.length <= 1}><Trash2 size={16} /></button></div><input className="title-input" value={product.title} onChange={(e) => updateProduct(index, { title: e.target.value })} /><div className="field-grid"><label>平台<input value={product.platform} onChange={(e) => updateProduct(index, { platform: e.target.value })} /></label><label>品牌<input value={product.brand} onChange={(e) => updateProduct(index, { brand: e.target.value })} /></label><label>型号<input value={product.model} onChange={(e) => updateProduct(index, { model: e.target.value })} /></label><label>页面价格<input type="number" min={0} value={product.price} onChange={(e) => updateProduct(index, { price: Number(e.target.value) })} /></label><label>优惠券<input type="number" min={0} value={product.coupon} onChange={(e) => updateProduct(index, { coupon: Number(e.target.value) })} /></label><label>平台优惠<input type="number" min={0} value={product.platform_discount} onChange={(e) => updateProduct(index, { platform_discount: Number(e.target.value) })} /></label></div><label className="check-row"><input type="checkbox" checked={product.official_store} onChange={(e) => updateProduct(index, { official_store: e.target.checked })} />官方/自营店铺</label></article>)}</div></div><div className="panel result-panel"><div className="section-heading"><div><span>第二步</span><h2>看懂这次购买</h2></div><ShieldCheck size={24} /></div>{result ? <div className="result-stack"><div className="recommend-card"><span>{best ? `推荐候选 ${best.index + 1}` : '需要补充信息'}</span><h3>{result.result.summary}</h3><p>{result.result.recommendation_reason}</p></div><div className="comparison-table"><div className="table-row table-head"><span>商品</span><span>到手价</span><span>同款</span><span>风险</span><span>适配</span></div>{result.result.comparison_rows.map((row) => <div className="table-row" key={row.index}><strong>{row.title}</strong><span>{money(row.final_price)}</span><span>{row.same_item_relation === 'same' ? '同款' : row.same_item_relation === 'uncertain' ? '待确认' : '有差异'}</span><span className={`risk risk-${row.risk_level}`}>{riskLabel[row.risk_level] ?? row.risk_level}</span><span>{row.suitable_for_user ? '适合' : '谨慎'}</span></div>)}</div><div className="risk-grid">{result.result.risk_reports.map((risk, index) => <article key={index}><ShieldCheck size={20} /><strong>候选 {index + 1} · {riskLabel[risk.overall_risk] ?? risk.overall_risk}</strong><p>{risk.reasons.slice(0, 2).join('；') || '暂未发现明显风险。'}</p></article>)}</div><details className="report-details"><summary><FileText size={16} />查看完整决策报告</summary><pre>{result.result.report_markdown}</pre></details></div> : <div className="empty-result"><TagIcon /><h3>还没有分析结果</h3><p>确认商品价格和规格后，点击“立即分析”。</p></div>}</div></section>
    </>}
    {view === 'monitors' && <section className="page-section"><PageTitle icon={<Bell size={22} />} title="降价监控" subtitle="把“等等再买”交给 ValuSee，达到目标价再提醒你。" /><div className="management-grid"><form className="panel compact-form" onSubmit={createMonitor}><h3>新建监控</h3><label>商品<select value={monitorProduct} onChange={(e) => setMonitorProduct(Number(e.target.value))}>{products.map((p, i) => <option key={i} value={i}>{p.title}</option>)}</select></label><label>目标到手价<input type="number" min={0} value={targetPrice} onChange={(e) => setTargetPrice(Number(e.target.value))} /></label><button className="primary-button"><Bell size={17} />创建监控</button></form><div className="panel list-panel"><h3>正在关注的商品 <span>{monitors.length}</span></h3>{monitors.length ? monitors.map((item) => <article className="record-row" key={item.monitor_id}><div><strong>{item.product.title}</strong><span>{item.product.platform} · 当前 {money(item.current_final_price)} · 目标 {money(item.target_price)}</span></div><b className={item.status === 'target_reached' ? 'status-good' : ''}>{item.status === 'target_reached' ? '已到目标价' : '监控中'}</b><small>至 {date(item.expires_at)}</small></article>) : <Empty text="还没有价格监控" />}</div></div></section>}
    {view === 'purchases' && <section className="page-section"><PageTitle icon={<Receipt size={22} />} title="我的购买" subtitle="记录实际支付价格，及时抓住保价、退货和保修节点。" /><div className="management-grid"><form className="panel compact-form" onSubmit={createPurchase}><h3>记录一笔购买</h3><label>商品<select value={purchaseProduct} onChange={(e) => setPurchaseProduct(Number(e.target.value))}>{products.map((p, i) => <option key={i} value={i}>{p.title}</option>)}</select></label><label>实际支付<input type="number" min={0} value={paidPrice || products[purchaseProduct]?.price || 0} onChange={(e) => setPaidPrice(Number(e.target.value))} /></label><button className="primary-button"><Receipt size={17} />保存购买</button></form><div className="panel list-panel"><h3>购买记录 <span>{purchases.length}</span></h3>{purchases.length ? purchases.map((item) => <article className="purchase-card" key={item.purchase_id}><div className="purchase-head"><strong>{item.product.title}</strong><b>{money(item.paid_price)}</b></div><span>{item.platform || '平台待确认'} · 购买于 {date(item.purchased_at)}</span><div className="deadline-row"><i>保价至 {date(item.price_protection_deadline)}</i><i>退货至 {date(item.return_deadline)}</i><i>保修至 {date(item.warranty_deadline)}</i></div></article>) : <Empty text="还没有购买记录" />}</div></div></section>}
    {view === 'history' && <section className="page-section"><PageTitle icon={<History size={22} />} title="历史报告" subtitle="每次分析都会留在本机，方便回看你的购买判断。" /><div className="panel history-panel">{result ? <article className="history-card"><div><strong>{result.result.summary}</strong><span>任务 {result.task_id}</span></div><button className="soft-button" onClick={() => setView('analyze')}>打开报告 <ChevronRight size={16} /></button></article> : <Empty text="完成一次分析后，这里会出现你的报告" />}</div></section>}
  </main>;
}
function PageTitle({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle: string }) { return <div className="page-title"><div className="title-icon">{icon}</div><div><h1>{title}</h1><p>{subtitle}</p></div></div>; }
function Empty({ text }: { text: string }) { return <div className="empty-list"><ClipboardList size={28} /><span>{text}</span></div>; }
function TagIcon() { return <div className="empty-icon"><Search size={34} /></div>; }
