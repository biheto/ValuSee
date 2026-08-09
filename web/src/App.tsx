import {
  Bell,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Compass,
  Crown,
  Clock3,
  FileText,
  Download,
  ExternalLink,
  MessageSquareWarning,
  Pause,
  Play,
  Save,
  Settings,
  History,
  Heart,
  Link2,
  LogOut,
  Loader2,
  Plus,
  Receipt,
  Search,
  Share2,
  MessageSquare,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  Users,
  UserRound,
} from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { BrandMark, BrandWordmark, ValueMascot } from './BrandArt';
import { AccountHome, ConsumerNotification, ConsumerProduct, Dashboard, DiscoverPage, MessagesPage, MobileNav, ProductDetail, SavedItem, SavedPage, SharedDecisionPage } from './ConsumerHub';

type Product = ConsumerProduct;
type Decision = { task_id: string; status: string; result: {
  best_index: number | null; recommendation: string; recommendation_reason: string; summary: string;
  comparison_rows: Array<{ index: number; title: string; platform: string; model: string; same_item_relation: string; same_item_confidence: number; final_price: number; value_score: number; risk_level: string; suitable_for_user: boolean }>;
  price_breakdowns: Array<{ final_price: number }>;
  risk_reports: Array<{ overall_risk: string; reasons: string[] }>;
  report_markdown: string;
}; events: Array<{ node?: string; agent?: string; status?: string; content?: string; timestamp?: string }> };
type Monitor = { monitor_id: string; status: string; target_price: number; current_final_price: number; product: Product; expires_at: string; last_message: string };
type Purchase = { purchase_id: string; product: Product; paid_price: number; platform: string; store_name: string; purchased_at: string; price_protection_deadline?: string; return_deadline?: string; warranty_deadline?: string; status: string; reminders: Array<{ kind: string; deadline: string; label: string }>; notes: string };
type Capture = { capture_id: string; status: string; product: Product; source: string; captured_at: string };
type Notification = ConsumerNotification;
type ProductSearchResult = { provider: string; kind: string; product: Product };
type SavedReport = { report_id: string; task_id: string; goal: string; products: Product[]; result: Decision['result']; created_at: string };
type SavedComparison = { comparison_id: string; name: string; products: Product[]; updated_at: string };
type ShoppingProfile = { budget: number; devices: string[]; brand_preferences: string[]; sensitivities: string[]; acceptable_risk: string };
type NotificationPreference = { email_enabled: boolean; in_app_enabled: boolean; quiet_start: string | null; quiet_end: string | null };
type View = 'discover' | 'analyze' | 'monitors' | 'purchases' | 'saved' | 'messages' | 'account' | 'history' | 'family' | 'settings' | 'security' | 'membership';

/* Demo candidates are intentionally disabled: consumer UI must never imply that example.com prices are real. */
const sample: Product[] = [
  { title: 'AirPods Pro 2 USB-C 官方旗舰店', platform: '京东', url: 'https://example.com/jd-airpods', brand: 'Apple', model: 'AirPods Pro 2', sku: 'APP2-USBC', specs: { 接口: 'USB-C', 代次: '第二代' }, price: 1799, coupon: 140, platform_discount: 60, member_discount: 0, subsidy: 0, pay_discount: 20, shipping: 0, gift_value: 0, condition: '新品', official_store: true, return_days: 7, warranty_months: 12, notes: '官方店铺，适合 iPhone 用户。' },
  { title: 'AirPods Pro 2 Lightning 现货', platform: '拼多多', url: 'https://example.com/pdd-airpods', brand: 'Apple', model: 'AirPods Pro 2', sku: 'APP2-LIGHT', specs: { 接口: 'Lightning', 代次: '第二代' }, price: 1488, coupon: 80, platform_discount: 30, member_discount: 0, subsidy: 0, pay_discount: 0, shipping: 0, gift_value: 0, condition: '新品', official_store: false, return_days: 7, warranty_months: 12, notes: '价格更低，但接口和店铺资质需要确认。' },
];
const blank = (): Product => ({ title: '新商品候选', platform: '', url: '', brand: '', model: '', sku: '', specs: {}, price: 0, coupon: 0, platform_discount: 0, member_discount: 0, subsidy: 0, pay_discount: 0, shipping: 0, gift_value: 0, condition: '新品', official_store: false, return_days: 7, warranty_months: 12, notes: '' });

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = localStorage.getItem('valuesee-token');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(String(body.detail ?? `请求失败（${response.status}）`)); }
  return response.json();
}
const money = (value: number) => `¥${Number(value || 0).toFixed(0)}`;
const date = (value?: string) => value ? new Date(value).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) : '未设置';
const riskLabel: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险' };

export function App() {
  const [view, setView] = useState<View>('discover');
  const [goal, setGoal] = useState('想买一副适合 iPhone 的降噪耳机，预算 1800 元以内');
  const [budget, setBudget] = useState(1800);
  const [products, setProducts] = useState<Product[]>([]);
  const [result, setResult] = useState<Decision | null>(null);
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [purchases, setPurchases] = useState<Purchase[]>([]);
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [savedItems, setSavedItems] = useState<SavedItem[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard>({});
  const [detailProduct, setDetailProduct] = useState<Product | null>(null);
  const [publicShare, setPublicShare] = useState<{ title: string; share_type: string; payload: Record<string, unknown>; expires_at: string } | null | undefined>(undefined);
  const [reports, setReports] = useState<SavedReport[]>([]);
  const [comparisons, setComparisons] = useState<SavedComparison[]>([]);
  const [profile, setProfile] = useState<ShoppingProfile>({ budget: 1800, devices: [], brand_preferences: [], sensitivities: ['售后', '兼容性'], acceptable_risk: 'medium' });
  const [notificationPreference, setNotificationPreference] = useState<NotificationPreference>({ email_enabled: true, in_app_enabled: true, quiet_start: null, quiet_end: null });
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [monitorProduct, setMonitorProduct] = useState(0);
  const [targetPrice, setTargetPrice] = useState(1300);
  const [purchaseProduct, setPurchaseProduct] = useState(0);
  const [paidPrice, setPaidPrice] = useState(0);
  const [accountOpen, setAccountOpen] = useState(false);
  const [accountMode, setAccountMode] = useState<'login' | 'register' | 'forgot' | 'reset'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [resetToken, setResetToken] = useState(new URLSearchParams(window.location.search).get('reset_token') || '');
  const [accountName, setAccountName] = useState(localStorage.getItem('valuesee-account-name') || '本地账户');

  const refreshRecords = async () => {
    try {
      const [m, p, c, n, savedReports, savedComparisons, savedProfile, preferences, saved, overview] = await Promise.all([
        request<Monitor[]>('/api/v1/shopping/monitors'), request<Purchase[]>('/api/v1/shopping/purchases'),
        request<Capture[]>('/api/v1/shopping/extension/captures'), request<Notification[]>('/api/v1/shopping/notifications'),
        request<SavedReport[]>('/api/v1/shopping/reports'), request<SavedComparison[]>('/api/v1/shopping/comparisons'),
        request<{ profile: Partial<ShoppingProfile> }>('/api/v1/shopping/profile'),
        request<NotificationPreference>('/api/v1/shopping/notification-preferences'),
        request<SavedItem[]>('/api/v1/shopping/saved'), request<Dashboard>('/api/v1/shopping/dashboard'),
      ]);
      setMonitors(m); setPurchases(p); setCaptures(c.filter((item) => item.status === 'pending_confirmation')); setNotifications(n);
      setReports(savedReports); setComparisons(savedComparisons); setNotificationPreference(preferences);
      setSavedItems(saved); setDashboard(overview);
      if (Object.keys(savedProfile.profile || {}).length) {
        setProfile((current) => ({ ...current, ...savedProfile.profile }));
        setBudget(Number(savedProfile.profile.budget || 1800));
      }
    } catch { /* backend may be offline while the static preview is open */ }
  };
  useEffect(() => { void refreshRecords(); }, []);
  useEffect(() => { const match = window.location.pathname.match(/^\/share\/([a-f0-9]+)$/); if (match) void request<typeof publicShare>(`/api/v1/public/shares/${match[1]}`).then((data) => setPublicShare(data ?? null)).catch(() => setPublicShare(null)); }, []);
  useEffect(() => {
    const saved = localStorage.getItem('valuesee-last-report');
    if (saved) {
      try { setResult(JSON.parse(saved) as Decision); } catch { localStorage.removeItem('valuesee-last-report'); }
    }
  }, []);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const verifyToken = params.get('verify_token');
    if (verifyToken) {
      void request('/api/v1/auth/email/verify/confirm', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: verifyToken }) })
        .then(() => setMessage('邮箱验证成功。'))
        .catch((err) => setError(err instanceof Error ? err.message : '邮箱验证失败'));
      window.history.replaceState({}, '', window.location.pathname);
    }
    if (params.get('reset_token')) { setAccountMode('reset'); setAccountOpen(true); }
  }, []);

  async function runDecision(event?: FormEvent) {
    event?.preventDefault(); setLoading(true); setError('');
    try { const data = await request<Decision>('/api/v1/shopping/decide', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ goal, products, profile: { ...profile, budget, use_case: goal }, require_human_review: false }) }); setResult(data); setMessage('分析完成，报告已保存到账户。'); localStorage.setItem('valuesee-last-report', JSON.stringify(data)); await refreshRecords(); } catch (err) { setError(err instanceof Error ? err.message : '分析失败'); } finally { setLoading(false); }
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
  async function addProduct(product: Product, openDetail = false) { setProducts((items) => items.some((item) => item.url && item.url === product.url) ? items : [...items, product]); if (product.url) { await request('/api/v1/shopping/saved', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ item_type: 'recent', reference_key: product.url, label: product.title, product }) }).catch(() => undefined); } if (openDetail) setDetailProduct(product); await refreshRecords(); }
  async function toggleFavorite(product: Product) { const key = product.url || `${product.brand}:${product.model}:${product.sku}`; const existing = savedItems.find((item) => item.item_type === 'favorite' && item.reference_key === key); if (existing) await request(`/api/v1/shopping/saved/${existing.saved_id}`, { method: 'DELETE' }); else await request('/api/v1/shopping/saved', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ item_type: 'favorite', reference_key: key, label: product.title, product }) }); await refreshRecords(); }
  async function deleteSaved(id: string) { await request(`/api/v1/shopping/saved/${id}`, { method: 'DELETE' }); await refreshRecords(); }
  async function readMessage(id: string) { await request(`/api/v1/shopping/notifications/${id}/read`, { method: 'PATCH' }); await refreshRecords(); }
  async function readAllMessages() { await request('/api/v1/shopping/notifications/read-all', { method: 'POST' }); await refreshRecords(); }
  async function shareSnapshot(shareType: 'comparison' | 'report', title: string, payload: Record<string, unknown>) { try { const share = await request<{ share_url: string }>('/api/v1/shopping/shares', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ share_type: shareType, title, payload, expires_days: 30 }) }); const url = new URL(share.share_url, window.location.origin).toString(); let copied = false; try { if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(url); copied = true; } } catch { /* Clipboard access may be denied outside a secure context. */ } if (!copied) window.prompt('分享链接已生成，请复制：', url); setMessage(copied ? '分享链接已复制到剪贴板。' : `分享链接已生成：${url}`); } catch (err) { setError(err instanceof Error ? err.message : '生成分享链接失败'); } }
  function updateProduct(index: number, patch: Partial<Product>) { setProducts((items) => items.map((item, i) => i === index ? { ...item, ...patch } : item)); }
  async function createMonitor(event: FormEvent) { event.preventDefault(); const product = products[monitorProduct]; try { await request<Monitor>('/api/v1/shopping/monitors', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ product, target_price: targetPrice, monitor_days: 30, notify_channel: 'in_app' }) }); setMessage('降价监控已创建，服务重启后仍会保留。'); await refreshRecords(); } catch (err) { setError(err instanceof Error ? err.message : '创建监控失败'); } }
  async function createPurchase(event: FormEvent) { event.preventDefault(); const product = products[purchaseProduct]; try { await request<Purchase>('/api/v1/shopping/purchases', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ product, paid_price: paidPrice || product.price, platform: product.platform, store_name: product.official_store ? '官方/自营店' : '待确认', price_protection_days: 7, return_days: product.return_days, warranty_months: product.warranty_months, notes: '由 ValuSee 记录，提醒仅供参考。' }) }); setMessage('购买记录已保存，保价和退货提醒已建立。'); await refreshRecords(); } catch (err) { setError(err instanceof Error ? err.message : '保存购买记录失败'); } }
  async function saveComparison() { if (!products.length) return; try { await request('/api/v1/shopping/comparisons', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: goal.slice(0, 32) || '购物对比', products }) }); setMessage('对比清单已保存。'); await refreshRecords(); } catch (err) { setError(err instanceof Error ? err.message : '保存清单失败'); } }
  async function removeComparison(id: string) { try { await request(`/api/v1/shopping/comparisons/${encodeURIComponent(id)}`, { method: 'DELETE' }); await refreshRecords(); } catch (err) { setError(err instanceof Error ? err.message : '删除清单失败'); } }
  async function updateMonitor(monitor: Monitor, action: 'toggle' | 'price' | 'delete') { try { if (action === 'delete') await request(`/api/v1/shopping/monitors/${monitor.monitor_id}`, { method: 'DELETE' }); else { const nextPrice = action === 'price' ? Number(window.prompt('新的目标到手价', String(monitor.target_price))) : monitor.target_price; if (!nextPrice) return; await request(`/api/v1/shopping/monitors/${monitor.monitor_id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target_price: nextPrice, status: action === 'toggle' ? (monitor.status === 'paused' ? 'watching' : 'paused') : undefined }) }); } await refreshRecords(); } catch (err) { setError(err instanceof Error ? err.message : '更新监控失败'); } }
  async function sendFeedback(type: string, targetId: string) { const content = window.prompt('请说明哪里不准确，我们会保留证据并改进结果。'); if (!content?.trim()) return; try { await request('/api/v1/shopping/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ feedback_type: type, target_type: 'report', target_id: targetId, content, evidence: { goal, products } }) }); setMessage('反馈已提交，感谢你帮助修正结果。'); } catch (err) { setError(err instanceof Error ? err.message : '反馈提交失败'); } }
  async function acceptRecommendation(targetId: string) { try { await request('/api/v1/shopping/events', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event_type: 'recommendation_accepted', reference_id: targetId, idempotency_key: `accept:${targetId}` }) }); setMessage('已记录你的选择，后续推荐会更贴合你。'); } catch (err) { setError(err instanceof Error ? err.message : '记录选择失败'); } }
  async function saveSettings(event: FormEvent) { event.preventDefault(); try { await Promise.all([request('/api/v1/shopping/profile', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...profile, budget }) }), request('/api/v1/shopping/notification-preferences', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(notificationPreference) })]); setMessage('购物偏好与提醒设置已保存。'); await refreshRecords(); } catch (err) { setError(err instanceof Error ? err.message : '保存设置失败'); } }
  async function submitAccount(event: FormEvent) { event.preventDefault(); setError(''); try { if (accountMode === 'forgot') { await request('/api/v1/auth/password/reset/request', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email }) }); setMessage('如果邮箱已注册，重置邮件将很快送达。'); setAccountMode('login'); return; } if (accountMode === 'reset') { await request('/api/v1/auth/password/reset/confirm', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: resetToken, new_password: password }) }); setMessage('密码已更新，请重新登录。'); setResetToken(''); setAccountMode('login'); window.history.replaceState({}, '', window.location.pathname); return; } const data = await request<{ access_token: string; user: { display_name: string } }>(`/api/v1/auth/${accountMode}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password, display_name: displayName }) }); localStorage.setItem('valuesee-token', data.access_token); localStorage.setItem('valuesee-account-name', data.user.display_name); setAccountName(data.user.display_name); setAccountOpen(false); setMessage(accountMode === 'login' ? '登录成功。' : '账户创建成功，请查收验证邮件。'); await refreshRecords(); } catch (err) { setError(err instanceof Error ? err.message : '账户操作失败'); } }
  function logout() { localStorage.removeItem('valuesee-token'); localStorage.removeItem('valuesee-account-name'); setAccountName('本地账户'); setAccountOpen(false); void refreshRecords(); }

  const best = useMemo(() => result?.result.best_index == null ? null : result.result.comparison_rows[result.result.best_index], [result]);
  if (window.location.pathname.startsWith('/share/')) return <SharedDecisionPage share={publicShare} />;
  const nav: Array<[View, string, typeof Search]> = [['discover', '发现', Compass], ['analyze', '智能对比', Search], ['monitors', '省钱中心', Bell], ['purchases', '订单售后', Receipt], ['saved', '收藏足迹', Heart], ['messages', '消息', MessageSquare], ['account', '我的', UserRound]];
  return <main className="valuesee-app">
    <header className="app-header"><div className="brand-lockup"><BrandMark /><div><strong>ValuSee</strong><span>买之前，先看清价值</span></div></div><nav>{nav.map(([key, label, Icon]) => <button className={view === key ? 'active' : ''} key={key} onClick={() => setView(key)}><Icon size={17} />{label}</button>)}</nav><button className="profile-button" onClick={() => setAccountOpen(true)}>{accountName}</button></header>
    {accountOpen && <AccountDialog mode={accountMode} email={email} password={password} displayName={displayName} onEmail={setEmail} onPassword={setPassword} onDisplayName={setDisplayName} onMode={setAccountMode} onSubmit={submitAccount} onClose={() => setAccountOpen(false)} onLogout={logout} />}
    {message && <div className="toast"><CheckCircle2 size={16} />{message}<button onClick={() => setMessage('')}>关闭</button></div>}
    {error && <div className="error-banner">{error}</div>}
    {view === 'discover' && <DiscoverPage dashboard={dashboard} recent={savedItems.filter((item) => item.item_type === 'recent')} onStart={(nextGoal) => { setGoal(nextGoal); setView('analyze'); }} onOpen={(product) => void addProduct(product, true)} />}
    {view === 'saved' && <SavedPage items={savedItems} onOpen={(product) => void addProduct(product, true)} onDelete={(id) => void deleteSaved(id)} />}
    {view === 'messages' && <MessagesPage notifications={notifications} onRead={(id) => void readMessage(id)} onReadAll={() => void readAllMessages()} />}
    {view === 'account' && <AccountHome name={accountName} dashboard={dashboard} onNavigate={(next) => setView(next as View)} onLogin={() => setAccountOpen(true)} />}
    {view === 'analyze' && <>
      <section className="hero"><div className="hero-copy"><div className="eyebrow"><Sparkles size={16} />AI 购物决策助手</div><h1>别只看便不便宜，先看它值不值得。</h1><p>识别真假同款，算清真实到手价，结合你的预算和设备给出建议。买完之后，继续帮你盯住降价与保价。</p><form className="decision-box" onSubmit={runDecision}><textarea value={goal} onChange={(e) => setGoal(e.target.value)} /><div className="decision-controls"><label>预算 <input type="number" min={0} value={budget} onChange={(e) => setBudget(Number(e.target.value))} /> 元</label><button type="submit" disabled={loading}>{loading ? <Loader2 className="spin" size={18} /> : <Search size={18} />}立即分析</button></div></form></div><div className="hero-aside"><div className="hero-visual"><ValueMascot /><div className="visual-badge">看清价值，再决定</div></div></div></section>
      <section className="quick-strip"><button onClick={() => setGoal('帮我选一台适合代码办公的 27 英寸显示器，预算 2500 元')}><Search size={20} /><strong>帮我选</strong><span>输入需求，得到适配候选</span><ChevronRight size={17} /></button><button onClick={() => document.getElementById('products')?.scrollIntoView({ behavior: 'smooth' })}><Link2 size={20} /><strong>帮我比</strong><span>添加链接，识别是否同款</span><ChevronRight size={17} /></button><button onClick={() => setView('monitors')}><Clock3 size={20} /><strong>等等再买</strong><span>到目标价再提醒我</span><ChevronRight size={17} /></button></section>
      <ProductSearchPanel onAdd={(product) => void addProduct(product, true)} />
      {products.length > 0 && <div className="comparison-savebar"><div><strong>{products.length} 个候选商品</strong><span>保存后可在“报告与清单”继续比较</span></div><button className="soft-button" onClick={() => void saveComparison()}><Save size={17} />保存当前清单</button></div>}
      {result && <><DecisionEvidence events={result.events} /><div className="feedback-bar"><MessageSquareWarning size={18} /><span>这份建议对你有帮助吗？</span><button onClick={() => void acceptRecommendation(result.task_id)}>有帮助</button><span>发现问题：</span><button onClick={() => void sendFeedback('wrong_sku', result.task_id)}>规格有误</button><button onClick={() => void sendFeedback('wrong_price', result.task_id)}>价格有误</button><button onClick={() => void sendFeedback('wrong_recommendation', result.task_id)}>建议不合适</button></div></>}
      {captures.length > 0 && <section className="capture-inbox"><div><strong>浏览器采集收件箱</strong><span>这些商品来自你正在浏览的页面，确认后才会加入分析。</span></div><div className="capture-items">{captures.map((capture) => <article key={capture.capture_id}><div><b>{capture.product.title}</b><small>{capture.product.platform} · {capture.product.price ? money(capture.product.price) : '价格待确认'}</small></div><button onClick={() => void importCapture(capture)}>加入候选</button></article>)}</div></section>}
      <section className="workspace-grid" id="products"><div className="panel"><div className="section-heading"><div><span>第一步</span><h2>添加要比较的商品</h2></div><button className="soft-button" onClick={() => setProducts((items) => [...items, blank()])}><Plus size={17} />手动添加</button></div><form className="url-form" onSubmit={addUrl}><Link2 size={18} /><input placeholder="粘贴淘宝、京东、拼多多商品链接" value={url} onChange={(e) => setUrl(e.target.value)} /><button>读取链接</button><label className="upload-button"><Upload size={16} />识别截图<input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => e.target.files?.[0] && void addImage(e.target.files[0])} /></label></form><div className="product-list">{products.map((product, index) => <article className="product-editor" key={`${index}-${product.title}`}><div className="product-editor-head"><span>候选 {index + 1}</span><button className="icon-button" title="删除候选" onClick={() => setProducts((items) => items.filter((_, i) => i !== index))} disabled={products.length <= 1}><Trash2 size={16} /></button></div><input className="title-input" value={product.title} onChange={(e) => updateProduct(index, { title: e.target.value })} /><div className="field-grid"><label>平台<input value={product.platform} onChange={(e) => updateProduct(index, { platform: e.target.value })} /></label><label>品牌<input value={product.brand} onChange={(e) => updateProduct(index, { brand: e.target.value })} /></label><label>型号<input value={product.model} onChange={(e) => updateProduct(index, { model: e.target.value })} /></label><label>页面价格<input type="number" min={0} value={product.price} onChange={(e) => updateProduct(index, { price: Number(e.target.value) })} /></label><label>优惠券<input type="number" min={0} value={product.coupon} onChange={(e) => updateProduct(index, { coupon: Number(e.target.value) })} /></label><label>平台优惠<input type="number" min={0} value={product.platform_discount} onChange={(e) => updateProduct(index, { platform_discount: Number(e.target.value) })} /></label></div><label className="check-row"><input type="checkbox" checked={product.official_store} onChange={(e) => updateProduct(index, { official_store: e.target.checked })} />官方/自营店铺</label></article>)}</div></div><div className="panel result-panel"><div className="section-heading"><div><span>第二步</span><h2>看懂这次购买</h2></div><ShieldCheck size={24} /></div>{result ? <div className="result-stack"><div className="recommend-card"><span>{best ? `推荐候选 ${best.index + 1}` : '需要补充信息'}</span><h3>{result.result.summary}</h3><p>{result.result.recommendation_reason}</p></div><div className="comparison-table"><div className="table-row table-head"><span>商品</span><span>到手价</span><span>同款</span><span>风险</span><span>适配</span></div>{result.result.comparison_rows.map((row) => <div className="table-row" key={row.index}><strong>{row.title}</strong><span>{money(row.final_price)}</span><span>{row.same_item_relation === 'same' ? '同款' : row.same_item_relation === 'uncertain' ? '待确认' : '有差异'}</span><span className={`risk risk-${row.risk_level}`}>{riskLabel[row.risk_level] ?? row.risk_level}</span><span>{row.suitable_for_user ? '适合' : '谨慎'}</span></div>)}</div><div className="risk-grid">{result.result.risk_reports.map((risk, index) => <article key={index}><ShieldCheck size={20} /><strong>候选 {index + 1} · {riskLabel[risk.overall_risk] ?? risk.overall_risk}</strong><p>{risk.reasons.slice(0, 2).join('；') || '暂未发现明显风险。'}</p></article>)}</div><details className="report-details"><summary><FileText size={16} />查看完整决策报告</summary><pre>{result.result.report_markdown}</pre></details></div> : <div className="empty-result"><TagIcon /><h3>还没有分析结果</h3><p>确认商品价格和规格后，点击“立即分析”。</p></div>}</div></section>
    </>}
    {view === 'monitors' && <MonitorControls monitors={monitors} onAction={updateMonitor} />}
    {view === 'monitors' && <section className="page-section"><PageTitle icon={<Bell size={22} />} title="降价监控" subtitle="把“等等再买”交给 ValuSee，达到目标价再提醒你。" />{notifications.length > 0 && <div className="notification-list">{notifications.map((item) => <article key={item.notification_id}><Bell size={17} /><div><strong>{item.title}</strong><span>{item.message}</span></div><small>{date(item.created_at)}</small></article>)}</div>}<div className="management-grid"><form className="panel compact-form" onSubmit={createMonitor}><h3>新建监控</h3><label>商品<select value={monitorProduct} onChange={(e) => setMonitorProduct(Number(e.target.value))}>{products.map((p, i) => <option key={i} value={i}>{p.title}</option>)}</select></label><label>目标到手价<input type="number" min={0} value={targetPrice} onChange={(e) => setTargetPrice(Number(e.target.value))} /></label><button className="primary-button"><Bell size={17} />创建监控</button></form><div className="panel list-panel"><h3>正在关注的商品 <span>{monitors.length}</span></h3>{monitors.length ? monitors.map((item) => <article className="record-row" key={item.monitor_id}><div><strong>{item.product.title}</strong><span>{item.product.platform} · 当前 {money(item.current_final_price)} · 目标 {money(item.target_price)}</span></div><b className={item.status === 'target_reached' ? 'status-good' : ''}>{item.status === 'target_reached' ? '已到目标价' : '监控中'}</b><small>至 {date(item.expires_at)}</small></article>) : <Empty text="还没有价格监控" />}</div></div></section>}
    {view === 'purchases' && <section className="page-section"><PageTitle icon={<Receipt size={22} />} title="我的购买" subtitle="记录实际支付价格，及时抓住保价、退货和保修节点。" /><div className="management-grid"><form className="panel compact-form" onSubmit={createPurchase}><h3>记录一笔购买</h3><label>商品<select value={purchaseProduct} onChange={(e) => setPurchaseProduct(Number(e.target.value))}>{products.map((p, i) => <option key={i} value={i}>{p.title}</option>)}</select></label><label>实际支付<input type="number" min={0} value={paidPrice || products[purchaseProduct]?.price || 0} onChange={(e) => setPaidPrice(Number(e.target.value))} /></label><button className="primary-button"><Receipt size={17} />保存购买</button></form><div className="panel list-panel"><h3>购买记录 <span>{purchases.length}</span></h3>{purchases.length ? purchases.map((item) => <article className="purchase-card" key={item.purchase_id}><div className="purchase-head"><strong>{item.product.title}</strong><b>{money(item.paid_price)}</b></div><span>{item.platform || '平台待确认'} · 购买于 {date(item.purchased_at)}</span><div className="deadline-row"><i>保价至 {date(item.price_protection_deadline)}</i><i>退货至 {date(item.return_deadline)}</i><i>保修至 {date(item.warranty_deadline)}</i></div></article>) : <Empty text="还没有购买记录" />}</div></div></section>}
    {view === 'history' && <SavedWork reports={reports} comparisons={comparisons} onOpenReport={(report) => { setResult({ task_id: report.task_id, status: 'completed', result: report.result, events: [] }); setProducts(report.products); setGoal(report.goal); setView('analyze'); }} onOpenComparison={(comparison) => { setProducts(comparison.products); setGoal(comparison.name); setView('analyze'); }} onDeleteComparison={removeComparison} onShareReport={(report) => void shareSnapshot('report', report.goal, { products: report.products, result: report.result })} onShareComparison={(comparison) => void shareSnapshot('comparison', comparison.name, { products: comparison.products })} />}
    {view === 'family' && <FamilyPanel />}
    {view === 'settings' && <SettingsPanel profile={profile} budget={budget} preferences={notificationPreference} onProfile={setProfile} onBudget={setBudget} onPreferences={setNotificationPreference} onSubmit={saveSettings} />}
    {view === 'security' && <SecurityPanel onLoggedOut={logout} />}
    {view === 'membership' && <MembershipPanel />}
    {detailProduct && <ProductDetail product={detailProduct} favorite={savedItems.some((item) => item.item_type === 'favorite' && item.reference_key === (detailProduct.url || `${detailProduct.brand}:${detailProduct.model}:${detailProduct.sku}`))} onClose={() => setDetailProduct(null)} onFavorite={() => void toggleFavorite(detailProduct)} onCompare={() => { void addProduct(detailProduct); setDetailProduct(null); setView('analyze'); }} request={request} />}
    <MobileNav view={view} onChange={(next) => setView(next as View)} />
  </main>;
}
function MonitorControls({ monitors, onAction }: { monitors: Monitor[]; onAction: (monitor: Monitor, action: 'toggle' | 'price' | 'delete') => Promise<void> }) {
  if (!monitors.length) return null;
  return <section className="monitor-controls panel"><div className="section-heading"><div><span>任务管理</span><h2>调整正在运行的监控</h2></div></div><div>{monitors.map((monitor) => <article key={monitor.monitor_id}><div><strong>{monitor.product.title}</strong><span>目标 {money(monitor.target_price)} · {monitor.status === 'paused' ? '已暂停' : '运行中'}</span></div><div className="row-actions"><button title={monitor.status === 'paused' ? '继续监控' : '暂停监控'} onClick={() => void onAction(monitor, 'toggle')}>{monitor.status === 'paused' ? <Play size={15} /> : <Pause size={15} />}</button><button onClick={() => void onAction(monitor, 'price')}>改目标价</button><button className="danger" title="删除监控" onClick={() => void onAction(monitor, 'delete')}><Trash2 size={15} /></button></div></article>)}</div></section>;
}

function SavedWork({ reports, comparisons, onOpenReport, onOpenComparison, onDeleteComparison, onShareReport, onShareComparison }: { reports: SavedReport[]; comparisons: SavedComparison[]; onOpenReport: (report: SavedReport) => void; onOpenComparison: (comparison: SavedComparison) => void; onDeleteComparison: (id: string) => Promise<void>; onShareReport: (report: SavedReport) => void; onShareComparison: (comparison: SavedComparison) => void }) {
  return <section className="page-section"><PageTitle icon={<History size={22} />} title="报告与清单" subtitle="报告和候选清单保存在你的账户中，可在不同设备继续。" /><div className="saved-work-grid"><section className="panel list-panel"><h3>购买决策报告 <span>{reports.length}</span></h3>{reports.length ? reports.map((report) => <article className="history-card" key={report.report_id}><div><strong>{report.result.summary || report.goal}</strong><span>{date(report.created_at)} · {report.products.length} 个候选</span></div><div className="row-actions"><button title="分享报告" onClick={() => onShareReport(report)}><Share2 size={15} /></button><button className="soft-button" onClick={() => onOpenReport(report)}>打开 <ChevronRight size={16} /></button></div></article>) : <Empty text="完成分析后，报告会安全保存在这里" />}</section><section className="panel list-panel"><h3>已保存清单 <span>{comparisons.length}</span></h3>{comparisons.length ? comparisons.map((comparison) => <article className="history-card" key={comparison.comparison_id}><div><strong>{comparison.name}</strong><span>{date(comparison.updated_at)} · {comparison.products.length} 个候选</span></div><div className="row-actions"><button title="分享清单" onClick={() => onShareComparison(comparison)}><Share2 size={15} /></button><button className="soft-button" onClick={() => onOpenComparison(comparison)}>继续比较</button><button className="danger icon-button" title="删除清单" onClick={() => void onDeleteComparison(comparison.comparison_id)}><Trash2 size={15} /></button></div></article>) : <Empty text="保存候选商品后，可稍后继续比较" />}</section></div></section>;
}

function SettingsPanel({ profile, budget, preferences, onProfile, onBudget, onPreferences, onSubmit }: { profile: ShoppingProfile; budget: number; preferences: NotificationPreference; onProfile: (value: ShoppingProfile) => void; onBudget: (value: number) => void; onPreferences: (value: NotificationPreference) => void; onSubmit: (event: FormEvent) => Promise<void> }) {
  const list = (value: string) => value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);
  return <section className="page-section"><PageTitle icon={<Settings size={22} />} title="偏好设置" subtitle="让每次推荐都结合你的预算、已有设备和可接受风险。" /><form className="settings-grid" onSubmit={onSubmit}><section className="panel compact-form"><h3>购物档案</h3><label>常用预算<input type="number" min={0} value={budget} onChange={(event) => onBudget(Number(event.target.value))} /></label><label>已有设备<textarea value={profile.devices.join('，')} onChange={(event) => onProfile({ ...profile, devices: list(event.target.value) })} placeholder="MacBook Pro，iPhone 15" /></label><label>偏好品牌<textarea value={profile.brand_preferences.join('，')} onChange={(event) => onProfile({ ...profile, brand_preferences: list(event.target.value) })} placeholder="Apple，Sony" /></label><label>关注因素<textarea value={profile.sensitivities.join('，')} onChange={(event) => onProfile({ ...profile, sensitivities: list(event.target.value) })} placeholder="重量，续航，售后" /></label><label>可接受风险<select value={profile.acceptable_risk} onChange={(event) => onProfile({ ...profile, acceptable_risk: event.target.value })}><option value="low">只接受低风险</option><option value="medium">可接受适度风险</option><option value="high">价格优先</option></select></label></section><section className="panel compact-form"><h3>提醒方式</h3><label className="toggle-row"><input type="checkbox" checked={preferences.in_app_enabled} onChange={(event) => onPreferences({ ...preferences, in_app_enabled: event.target.checked })} /><span>站内提醒</span></label><label className="toggle-row"><input type="checkbox" checked={preferences.email_enabled} onChange={(event) => onPreferences({ ...preferences, email_enabled: event.target.checked })} /><span>邮件提醒</span></label><div className="quiet-grid"><label>静默开始<input type="time" value={preferences.quiet_start || ''} onChange={(event) => onPreferences({ ...preferences, quiet_start: event.target.value || null })} /></label><label>静默结束<input type="time" value={preferences.quiet_end || ''} onChange={(event) => onPreferences({ ...preferences, quiet_end: event.target.value || null })} /></label></div><p className="settings-note">静默时段仍会记录降价事件，但不会发送外部通知。</p><button className="primary-button"><Save size={17} />保存设置</button></section></form></section>;
}

function FamilyPanel() {
  const [families, setFamilies] = useState<Array<Record<string, unknown>>>([]);
  const [members, setMembers] = useState<Array<Record<string, unknown>>>([]);
  const [selected, setSelected] = useState('');
  const [name, setName] = useState('我的家庭');
  const [inviteEmail, setInviteEmail] = useState('');
  const [notice, setNotice] = useState('');
  async function load() {
    if (!localStorage.getItem('valuesee-token')) return;
    const rows = await request<Array<Record<string, unknown>>>('/api/v1/families');
    setFamilies(rows);
    const id = selected || String(rows[0]?.family_id || '');
    setSelected(id);
    if (id) setMembers(await request<Array<Record<string, unknown>>>(`/api/v1/families/${encodeURIComponent(id)}/members`));
  }
  useEffect(() => { void load(); }, []);
  async function create(event: FormEvent) { event.preventDefault(); await request('/api/v1/families', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) }); setNotice('家庭已创建。'); await load(); }
  async function invite(event: FormEvent) { event.preventDefault(); await request('/api/v1/families/invite', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ family_id: selected, email: inviteEmail }) }); setInviteEmail(''); setNotice('成员已加入家庭。'); await load(); }
  async function role(userId: string, nextRole: string) { await request(`/api/v1/families/${encodeURIComponent(selected)}/members/${encodeURIComponent(userId)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role: nextRole }) }); await load(); }
  async function remove(userId: string) { await request(`/api/v1/families/${encodeURIComponent(selected)}/members/${encodeURIComponent(userId)}`, { method: 'DELETE' }); await load(); }
  if (!localStorage.getItem('valuesee-token')) return <section className="page-section"><PageTitle icon={<Users size={22} />} title="我的家庭" subtitle="登录后可与家庭成员共享设备档案和购买提醒。" /><div className="panel"><Empty text="请先登录账户" /></div></section>;
  return <section className="page-section"><PageTitle icon={<Users size={22} />} title="我的家庭" subtitle="管理家庭商品、设备档案和成员权限。" />{notice && <div className="toast"><CheckCircle2 size={16} />{notice}</div>}<div className="management-grid"><section className="panel"><div className="section-heading"><div><span>家庭空间</span><h2>创建或选择家庭</h2></div></div><form className="family-form" onSubmit={create}><input required value={name} onChange={(e) => setName(e.target.value)} /><button className="primary-button">创建家庭</button></form><div className="family-list">{families.map((item) => <button key={String(item.family_id)} className={selected === String(item.family_id) ? 'active' : ''} onClick={async () => { const id = String(item.family_id); setSelected(id); setMembers(await request(`/api/v1/families/${encodeURIComponent(id)}/members`)); }}><strong>{String(item.name)}</strong><span>{String(item.role)}</span></button>)}</div></section><section className="panel"><div className="section-heading"><div><span>成员权限</span><h2>家庭成员</h2></div></div>{selected && <form className="family-form" onSubmit={invite}><input type="email" required placeholder="已注册成员邮箱" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} /><button className="primary-button">添加成员</button></form>}<div className="family-members">{members.map((item) => <article key={String(item.user_id)}><div><strong>{String(item.display_name)}</strong><span>{String(item.email)} · {String(item.role)}</span></div>{item.role !== 'owner' && <div><button onClick={() => void role(String(item.user_id), item.role === 'editor' ? 'member' : 'editor')}>{item.role === 'editor' ? '设为成员' : '允许编辑'}</button><button className="danger" onClick={() => void remove(String(item.user_id))}>移除</button></div>}</article>)}</div></section></div></section>;
}

type AccountSession = { session_id: string; device_name: string; ip_address?: string; status: string; current: boolean; created_at: string; last_seen_at: string; expires_at: string };

function SecurityPanel({ onLoggedOut }: { onLoggedOut: () => void }) {
  const [user, setUser] = useState<{ email?: string; email_verified?: boolean } | null>(null);
  const [sessions, setSessions] = useState<AccountSession[]>([]);
  const [notice, setNotice] = useState('');
  const load = async () => { const [me, active] = await Promise.all([request<{ user: { email?: string; email_verified?: boolean } }>('/api/v1/auth/me'), request<AccountSession[]>('/api/v1/auth/sessions')]); setUser(me.user); setSessions(active); };
  useEffect(() => { if (localStorage.getItem('valuesee-token')) void load().catch(() => setNotice('安全信息读取失败，请重新登录。')); }, []);
  async function revoke(item: AccountSession) { await request(`/api/v1/auth/sessions/${encodeURIComponent(item.session_id)}`, { method: 'DELETE' }); if (item.current) { onLoggedOut(); setNotice('当前设备已退出。'); } else { setNotice('该设备已退出。'); await load(); } }
  async function verifyEmail() { await request('/api/v1/auth/email/verify/request', { method: 'POST' }); setNotice('验证邮件已发送，请在 24 小时内完成。'); }
  async function exportData() { const data = await request<Record<string, unknown>>('/api/v1/auth/export'); const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `valuesee-account-${new Date().toISOString().slice(0, 10)}.json`; anchor.click(); URL.revokeObjectURL(url); setNotice('账户数据已导出。'); }
  async function deleteAccount() { const confirmation = window.prompt('此操作会永久删除账户和关联购物数据。请输入 DELETE 确认：'); if (confirmation !== 'DELETE') return; await request('/api/v1/auth/account', { method: 'DELETE' }); onLoggedOut(); setNotice('账户和关联数据已删除。'); }
  if (!localStorage.getItem('valuesee-token')) return <section className="page-section"><PageTitle icon={<ShieldCheck size={22} />} title="账户与数据安全" subtitle="登录后管理设备、邮箱和个人数据。" /><div className="panel"><Empty text="请先登录账户" /></div></section>;
  return <section className="page-section"><PageTitle icon={<ShieldCheck size={22} />} title="账户与数据安全" subtitle="控制登录设备、身份验证和数据生命周期。" />{notice && <div className="toast"><CheckCircle2 size={16} />{notice}</div>}<div className="settings-grid"><section className="panel compact-form"><h3>身份与数据</h3><div className="security-identity"><span>{user?.email || '邮箱读取中'}</span><b className={user?.email_verified ? 'verified' : ''}>{user?.email_verified ? '已验证' : '未验证'}</b></div>{!user?.email_verified && <button className="soft-button" onClick={() => void verifyEmail()}>发送验证邮件</button>}<button className="soft-button" onClick={() => void exportData()}><Download size={16} />导出我的数据</button><button className="danger-button" onClick={() => void deleteAccount()}><Trash2 size={16} />永久注销账户</button><p className="settings-note">注销会删除账户、监控、报告、购买记录、分享和家庭成员关系，无法恢复。</p></section><section className="panel compact-form"><h3>登录设备</h3><div className="session-list">{sessions.map((item) => <article key={item.session_id}><div><strong>{item.device_name || '未知设备'}{item.current && <em>当前</em>}</strong><span>{item.ip_address || 'IP 未记录'} · 最近活动 {date(item.last_seen_at)}</span></div>{item.status === 'active' && <button title="退出该设备" onClick={() => void revoke(item)}><LogOut size={16} /></button>}</article>)}</div></section></div></section>;
}

function MembershipPanel() {
  const [status, setStatus] = useState<{ plan_code: string; limits: Record<string, number> } | null>(null);
  const [plans, setPlans] = useState<Array<{ code: string; name: string; price: number | null; status?: string; benefits: string[] }>>([]);
  const [notice, setNotice] = useState('');
  useEffect(() => { void Promise.all([request<{ plan_code: string; limits: Record<string, number> }>('/api/v1/membership'), request<{ plans: typeof plans; payment_available: boolean }>('/api/v1/membership/plans')]).then(([member, catalog]) => { setStatus(member); setPlans(catalog.plans); }).catch(() => setNotice('登录后可查看会员权益。')); }, []);
  async function requestPro() { const result = await request<{ status: string }>('/api/v1/membership/upgrade-requests', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ plan_code: 'pro' }) }); setNotice(result.status === 'pending' ? '已加入 Pro 开通候补，支付接入后会通知你。' : '申请已记录。'); }
  return <section className="page-section"><PageTitle icon={<Crown size={22} />} title="会员权益" subtitle="额度与能力清晰可见，推荐排序不受会员或佣金影响。" />{notice && <div className="toast"><CheckCircle2 size={16} />{notice}</div>}<div className="membership-grid">{plans.map((plan) => <article className={`panel ${status?.plan_code === plan.code ? 'current' : ''}`} key={plan.code}><span>{status?.plan_code === plan.code ? '当前方案' : plan.status === 'coming_soon' ? '即将开放' : '方案'}</span><h2>{plan.name}</h2><strong>{plan.price == null ? (plan.code === 'free' ? '免费' : '价格待公布') : money(plan.price)}</strong><ul>{plan.benefits.map((benefit) => <li key={benefit}><CheckCircle2 size={15} />{benefit}</li>)}</ul>{plan.code === 'pro' && status?.plan_code !== 'pro' && <button className="primary-button" onClick={() => void requestPro()}>加入开通候补</button>}</article>)}</div>{status && <div className="panel quota-strip"><span>当前额度</span><b>{status.limits.active_monitors} 个监控</b><b>{status.limits.monthly_comparisons} 次/月对比</b><b>{status.limits.family_members} 位家庭成员</b></div>}</section>;
}
function AccountDialog({ mode, email, password, displayName, onEmail, onPassword, onDisplayName, onMode, onSubmit, onClose, onLogout }: { mode: 'login' | 'register' | 'forgot' | 'reset'; email: string; password: string; displayName: string; onEmail: (value: string) => void; onPassword: (value: string) => void; onDisplayName: (value: string) => void; onMode: (mode: 'login' | 'register' | 'forgot' | 'reset') => void; onSubmit: (event: FormEvent) => void; onClose: () => void; onLogout: () => void }) {
  const title = mode === 'login' ? '登录 ValuSee' : mode === 'register' ? '创建账户' : mode === 'forgot' ? '找回密码' : '设置新密码';
  const submitLabel = mode === 'login' ? '登录' : mode === 'register' ? '注册' : mode === 'forgot' ? '发送重置邮件' : '更新密码';
  return <div className="account-backdrop" onClick={onClose}><section className="account-dialog" onClick={(event) => event.stopPropagation()}><BrandWordmark /><h2>{title}</h2><p>{mode === 'forgot' ? '输入注册邮箱，我们会发送一次性重置链接。' : mode === 'reset' ? '新密码至少需要 8 个字符。' : '你的监控、购买记录和家庭数据会与账户隔离。'}</p><form onSubmit={onSubmit}>{mode === 'register' && <label>昵称<input value={displayName} onChange={(e) => onDisplayName(e.target.value)} /></label>}{mode !== 'reset' && <label>邮箱<input type="email" required value={email} onChange={(e) => onEmail(e.target.value)} /></label>}{mode !== 'forgot' && <label>密码<input type="password" required minLength={8} value={password} onChange={(e) => onPassword(e.target.value)} /></label>}<button className="primary-button">{submitLabel}</button></form>{mode === 'login' && <><button className="account-switch" onClick={() => onMode('register')}>没有账户？立即注册</button><button className="account-switch" onClick={() => onMode('forgot')}>忘记密码</button></>}{mode !== 'login' && mode !== 'reset' && <button className="account-switch" onClick={() => onMode('login')}>返回登录</button>}{localStorage.getItem('valuesee-token') && <button className="account-switch danger" onClick={onLogout}>退出登录</button>}</section></div>;
}
function ProductSearchPanel({ onAdd }: { onAdd: (product: Product) => void }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<ProductSearchResult[]>([]);
  const [sources, setSources] = useState<Array<{ provider: string; status: string; count?: number; error?: string }>>([]);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (query.trim().length < 2) return;
    setLoading(true); setMessage('');
    try {
      const data = await request<{ results: ProductSearchResult[]; sources: Array<{ provider: string; status: string; count?: number; error?: string }>; message: string }>('/api/v1/shopping/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query: query.trim(), limit: 12 }) });
      setResults(data.results); setSources(data.sources); setMessage(data.message);
    } catch (err) { setResults([]); setMessage(err instanceof Error ? err.message : '商品搜索失败'); }
    finally { setLoading(false); }
  }
  return <section className="product-search-panel"><div className="product-search-copy"><span className="section-kicker">商品来源</span><h2>先找到商品，再帮你看值不值得买</h2><p>只展示已授权来源返回的真实商品，并保留平台、价格和原始链接。没有可用来源时，请粘贴商品链接或使用浏览器扩展采集。</p></div><form className="product-search-form" onSubmit={submit}><Search size={18} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：AirPods Pro 2 USB-C、27 英寸 4K 显示器" /><button disabled={loading}>{loading ? '搜索中…' : '搜索商品'}</button></form><div className="platform-readiness"><span>京东 · 待授权</span><span>淘宝 / 天猫 · 待授权</span><span>拼多多 · 待授权</span></div>{message && <div className="search-message">{message}</div>}{sources.length > 0 && <div className="source-status">{sources.map((source) => <span key={source.provider} className={source.status === 'ok' ? 'source-ok' : 'source-error'}>{source.provider} · {source.status === 'ok' ? `${source.count ?? 0} 条` : '暂不可用'}</span>)}</div>}{results.length > 0 && <div className="product-search-results">{results.map((item) => <article className="product-search-result" key={`${item.provider}-${item.product.url}`}><div><strong>{item.product.title}</strong><span>{item.product.platform || item.provider} · {item.product.price ? money(item.product.price) : '价格待确认'} · {item.product.model || '型号待确认'}</span></div><div className="product-search-actions"><a href={item.product.url} target="_blank" rel="noreferrer"><ExternalLink size={14} />打开商品</a><button type="button" onClick={() => onAdd(item.product)}>加入比较</button></div></article>)}</div>}</section>;
}

function DecisionEvidence({ events }: { events: Decision['events'] }) {
  const labels = ['需求理解', '规格核对', '到手价计算', '风险检查', '适配度判断', '建议整理'];
  return <section className="agent-timeline"><div><span className="section-kicker">分析依据</span><strong>这份建议经过了哪些检查</strong></div><div className="agent-timeline-steps">{events.map((event, index) => <div className="agent-step" key={`${event.node}-${index}`}><i>{index + 1}</i><div><b>{labels[index] || '结果整理'}</b><span>{event.content || '已完成'}</span></div><em>已完成</em></div>)}</div></section>;
}

function PageTitle({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle: string }) { return <div className="page-title"><div className="title-icon">{icon}</div><div><h1>{title}</h1><p>{subtitle}</p></div></div>; }
function Empty({ text }: { text: string }) { return <div className="empty-list"><ClipboardList size={28} /><span>{text}</span></div>; }
function TagIcon() { return <div className="empty-icon"><Search size={34} /></div>; }
