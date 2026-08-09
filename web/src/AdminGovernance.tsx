import { FormEvent, useEffect, useState } from 'react';
import { Check, Eye, Pause, Play, Plus, RefreshCw, Trash2 } from 'lucide-react';

type Item = Record<string, unknown>;

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = localStorage.getItem('valuesee-token');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(String(body.detail ?? `请求失败：${response.status}`));
  return body as T;
}

export function AdminGovernance() {
  const [products, setProducts] = useState<Item[]>([]);
  const [prompts, setPrompts] = useState<Item[]>([]);
  const [benchmarks, setBenchmarks] = useState<Item[]>([]);
  const [monitors, setMonitors] = useState<Item[]>([]);
  const [feedback, setFeedback] = useState<Item[]>([]);
  const [content, setContent] = useState<Item[]>([]);
  const [tickets, setTickets] = useState<Item[]>([]);
  const [users, setUsers] = useState<Item[]>([]);
  const [upgrades, setUpgrades] = useState<Item[]>([]);
  const [campaigns, setCampaigns] = useState<Item[]>([]);
  const [riskRules, setRiskRules] = useState<Item[]>([]);
  const [shares, setShares] = useState<Item[]>([]);
  const [audits, setAudits] = useState<Item[]>([]);
  const [experiments, setExperiments] = useState<Item[]>([]);
  const [metrics, setMetrics] = useState<Record<string, unknown>>({});
  const [error, setError] = useState('');
  const [brand, setBrand] = useState('');
  const [model, setModel] = useState('');
  const [title, setTitle] = useState('');
  const [agent, setAgent] = useState('recommendation');
  const [promptVersion, setPromptVersion] = useState('recommendation.v1');
  const [promptTitle, setPromptTitle] = useState('购物推荐 Prompt');
  const [skuProductId, setSkuProductId] = useState('');
  const [skuCode, setSkuCode] = useState('');
  const [skuVariant, setSkuVariant] = useState('');
  const [benchmarkType, setBenchmarkType] = useState('rag');
  const [benchmarkBusy, setBenchmarkBusy] = useState(false);
  const [contentTitle, setContentTitle] = useState('');
  const [contentSummary, setContentSummary] = useState('');
  const [campaignTitle, setCampaignTitle] = useState('');
  const [campaignSummary, setCampaignSummary] = useState('');
  const [riskName, setRiskName] = useState('');
  const [riskPattern, setRiskPattern] = useState('');
  const [experimentCode, setExperimentCode] = useState('navigation-density');
  const [experimentName, setExperimentName] = useState('导航密度实验');

  async function load() {
    setError('');
    try {
      const [catalog, promptData, benchmarkData, monitorData, feedbackData, metricsData, contentData, ticketData, userData, upgradeData, campaignData, riskData, shareData, auditData, experimentData] = await Promise.all([
        api<{ products: Item[] }>('/api/v1/admin/catalog/products'),
        api<{ prompts: Item[] }>('/api/v1/admin/prompts'),
        api<{ runs: Item[] }>('/api/v1/admin/benchmarks'),
        api<{ monitors: Item[] }>('/api/v1/admin/monitors'),
        api<{ feedback: Item[] }>('/api/v1/admin/feedback'),
        api<Record<string, unknown>>('/api/v1/admin/metrics'),
        api<{ items: Item[] }>('/api/v1/admin/content'),
        api<{ tickets: Item[] }>('/api/v1/admin/support/tickets'),
        api<{ users: Item[] }>('/api/v1/admin/users'),
        api<{ requests: Item[] }>('/api/v1/admin/membership/upgrade-requests'),
        api<{ items: Item[] }>('/api/v1/admin/campaigns'),
        api<{ rules: Item[] }>('/api/v1/admin/risk-rules'),
        api<{ shares: Item[] }>('/api/v1/admin/shares'),
        api<{ audits: Item[] }>('/api/v1/admin/audits?limit=100'),
        api<{ experiments: Item[] }>('/api/v1/admin/experiments'),
      ]);
      setProducts(catalog.products); setPrompts(promptData.prompts); setBenchmarks(benchmarkData.runs); setMonitors(monitorData.monitors);
      setFeedback(feedbackData.feedback);
      setMetrics(metricsData);
      setContent(contentData.items);
      setTickets(ticketData.tickets);
      setUsers(userData.users); setUpgrades(upgradeData.requests); setCampaigns(campaignData.items); setRiskRules(riskData.rules); setShares(shareData.shares); setAudits(auditData.audits);
      setExperiments(experimentData.experiments);
      if (!skuProductId && catalog.products[0]) setSkuProductId(String(catalog.products[0].product_id));
    } catch (err) { setError(err instanceof Error ? err.message : '治理数据加载失败'); }
  }
  useEffect(() => { void load(); }, []);

  async function saveProduct(event: FormEvent) {
    event.preventDefault(); setError('');
    try {
      await api('/api/v1/admin/catalog/products', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ brand, model, title, category: 'digital', specs: {}, status: 'active' }) });
      setBrand(''); setModel(''); setTitle(''); await load();
    } catch (err) { setError(err instanceof Error ? err.message : '商品保存失败'); }
  }
  async function deleteProduct(id: string) { await api(`/api/v1/admin/catalog/products/${encodeURIComponent(id)}`, { method: 'DELETE' }); await load(); }
  async function saveSku(event: FormEvent) { event.preventDefault(); setError(''); try { await api('/api/v1/admin/catalog/skus', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ product_id: skuProductId, sku: skuCode, variant: skuVariant, specs: {}, status: 'active' }) }); setSkuCode(''); setSkuVariant(''); await load(); } catch (err) { setError(err instanceof Error ? err.message : 'SKU 保存失败'); } }
  async function deleteSku(id: string) { await api(`/api/v1/admin/catalog/skus/${encodeURIComponent(id)}`, { method: 'DELETE' }); await load(); }
  async function savePrompt(event: FormEvent) {
    event.preventDefault(); setError('');
    try {
      await api('/api/v1/admin/prompts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agent, prompt_version: promptVersion, title: promptTitle, is_active: true, system_suffix: '' }) });
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Prompt 保存失败'); }
  }
  async function monitorAction(id: string, action: string) {
    await api(`/api/v1/admin/monitors/${encodeURIComponent(id)}/action`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, reason: '管理端操作' }) });
    await load();
  }
  async function runBenchmark() { setBenchmarkBusy(true); setError(''); try { await api('/api/v1/admin/benchmarks/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ benchmark_type: benchmarkType, name: `${benchmarkType.toUpperCase()} 运营评测`, iterations: 1 }) }); await load(); } catch (err) { setError(err instanceof Error ? err.message : '评测运行失败'); } finally { setBenchmarkBusy(false); } }
  async function reviewFeedback(id: string, status: 'reviewing' | 'resolved') { await api(`/api/v1/admin/feedback/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) }); await load(); }
  async function saveContent(event: FormEvent) { event.preventDefault(); await api('/api/v1/admin/content', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content_type: 'guide', title: contentTitle, summary: contentSummary, body: contentSummary, category: '综合', status: 'published' }) }); setContentTitle(''); setContentSummary(''); await load(); }
  async function deleteContent(id: string) { await api(`/api/v1/admin/content/${encodeURIComponent(id)}`, { method: 'DELETE' }); await load(); }
  async function replyTicket(id: string, status: string) { const content = window.prompt('回复用户'); if (!content?.trim()) return; await api(`/api/v1/admin/support/tickets/${encodeURIComponent(id)}/messages`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content, status }) }); await load(); }
  async function updateUser(id: string, status: string) { await api(`/api/v1/admin/users/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) }); await load(); }
  async function updateUpgrade(id: string, status: string) { await api(`/api/v1/admin/membership/upgrade-requests/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) }); await load(); }
  async function saveCampaign(event: FormEvent) { event.preventDefault(); await api('/api/v1/admin/campaigns', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: campaignTitle, title: campaignTitle, summary: campaignSummary, placement: 'discover', status: 'published' }) }); setCampaignTitle(''); setCampaignSummary(''); await load(); }
  async function deleteCampaign(id: string) { await api(`/api/v1/admin/campaigns/${encodeURIComponent(id)}`, { method: 'DELETE' }); await load(); }
  async function saveRiskRule(event: FormEvent) { event.preventDefault(); await api('/api/v1/admin/risk-rules', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: `rule-${Date.now()}`, name: riskName, field_name: 'title', pattern: riskPattern, severity: 'high', action: 'warn', enabled: true }) }); setRiskName(''); setRiskPattern(''); await load(); }
  async function deleteRiskRule(id: string) { await api(`/api/v1/admin/risk-rules/${encodeURIComponent(id)}`, { method: 'DELETE' }); await load(); }
  async function revokeShare(id: string) { await api(`/api/v1/admin/shares/${encodeURIComponent(id)}`, { method: 'DELETE' }); await load(); }
  async function saveExperiment(event: FormEvent) { event.preventDefault(); await api('/api/v1/admin/experiments', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: experimentCode, name: experimentName, variants: ['control', 'compact'], status: 'running' }) }); await load(); }

  return <section className="admin-content governance-stack">
    {error && <div className="admin-error">{error}</div>}
    <div className="admin-grid">
      <section className="admin-panel"><div className="admin-panel-title"><h2>标准商品与 SKU</h2><span>{products.length} 个商品</span></div><form className="admin-inline-form" onSubmit={saveProduct}><input required placeholder="品牌" value={brand} onChange={(e) => setBrand(e.target.value)} /><input required placeholder="标准型号" value={model} onChange={(e) => setModel(e.target.value)} /><input required placeholder="商品名称" value={title} onChange={(e) => setTitle(e.target.value)} /><button title="新增标准商品"><Plus size={15} /></button></form>{products.length > 0 && <form className="admin-inline-form" onSubmit={saveSku}><select required value={skuProductId} onChange={(e) => setSkuProductId(e.target.value)}>{products.map((item) => <option key={String(item.product_id)} value={String(item.product_id)}>{String(item.title)}</option>)}</select><input required placeholder="SKU 编码" value={skuCode} onChange={(e) => setSkuCode(e.target.value)} /><input required placeholder="版本 / 颜色 / 套装" value={skuVariant} onChange={(e) => setSkuVariant(e.target.value)} /><button title="新增 SKU"><Plus size={15} /></button></form>}{products.length ? products.map((item) => <div key={String(item.product_id)}><div className="admin-row"><div><strong>{String(item.title)}</strong><span>{String(item.brand)} · {String(item.model)} · {Array.isArray(item.skus) ? item.skus.length : 0} 个 SKU</span></div><button className="admin-icon-button" title="删除商品" onClick={() => void deleteProduct(String(item.product_id))}><Trash2 size={14} /></button></div>{Array.isArray(item.skus) && item.skus.map((sku) => { const row = sku as Item; return <div className="admin-row admin-sub-row" key={String(row.sku_id)}><div><strong>{String(row.sku)}</strong><span>{String(row.variant || '标准版本')}</span></div><button className="admin-icon-button" title="删除 SKU" onClick={() => void deleteSku(String(row.sku_id))}><Trash2 size={13} /></button></div>; })}</div>) : <div className="admin-empty">尚未建立标准商品库</div>}</section>
      <section className="admin-panel"><div className="admin-panel-title"><h2>Prompt 发布</h2><span>{prompts.length} 个版本</span></div><form className="admin-inline-form" onSubmit={savePrompt}><input required placeholder="Agent" value={agent} onChange={(e) => setAgent(e.target.value)} /><input required placeholder="版本" value={promptVersion} onChange={(e) => setPromptVersion(e.target.value)} /><input required placeholder="标题" value={promptTitle} onChange={(e) => setPromptTitle(e.target.value)} /><button title="保存并激活"><Plus size={15} /></button></form>{prompts.slice(0, 8).map((item) => <div className="admin-row" key={`${item.agent}-${item.prompt_version}`}><div><strong>{String(item.title)}</strong><span>{String(item.agent)} · {String(item.prompt_version)}</span></div><b className={item.is_active ? 'status-ok' : ''}>{item.is_active ? '使用中' : '历史版'}</b></div>)}</section>
    </div>
    <div className="admin-grid">
      <section className="admin-panel"><div className="admin-panel-title"><h2>价格监控治理</h2><span>{monitors.length} 条</span></div>{monitors.length ? monitors.map((item) => { const id = String(item.monitor_id); const status = String(item.status); const product = item.product as Item | undefined; return <div className="admin-row" key={id}><div><strong>{String(product?.title ?? id)}</strong><span>目标 ¥{String(item.target_price)} · 当前 ¥{String(item.current_final_price)} · {status}</span></div><div className="admin-row-buttons">{status === 'paused' || status === 'expired' ? <button title="恢复" onClick={() => void monitorAction(id, 'resume')}><Play size={14} /></button> : <button title="暂停" onClick={() => void monitorAction(id, 'pause')}><Pause size={14} /></button>}<button title="重试" onClick={() => void monitorAction(id, 'retry')}><RefreshCw size={14} /></button></div></div>; }) : <div className="admin-empty">暂无监控任务</div>}</section>
      <section className="admin-panel"><div className="admin-panel-title"><h2>Benchmark 结果</h2><span>{benchmarks.length} 次</span></div><div className="benchmark-runner"><select value={benchmarkType} onChange={(e) => setBenchmarkType(e.target.value)}><option value="rag">RAG 检索</option><option value="llm">LLM Prompt</option><option value="workflow">Workflow</option><option value="collaboration">多 Agent 协作</option><option value="mcp">工具调用</option></select><button onClick={() => void runBenchmark()} disabled={benchmarkBusy}>{benchmarkBusy ? '运行中…' : '立即评测'}</button></div>{benchmarks.length ? benchmarks.slice(0, 10).map((item) => <div className="admin-row" key={String(item.run_id)}><div><strong>{String(item.name)}</strong><span>{String(item.benchmark_type)} · {String(item.status)}</span></div><b>{String(item.finished_at ?? item.started_at ?? '')}</b></div>) : <div className="admin-empty">暂无评测记录</div>}</section>
    </div>
    <section className="admin-panel"><div className="admin-panel-title"><h2>用户纠错反馈</h2><span>{feedback.filter((item) => item.status !== 'resolved').length} 条待处理</span></div>{feedback.length ? feedback.slice(0, 30).map((item) => <div className="admin-row" key={String(item.feedback_id)}><div><strong>{String(item.content)}</strong><span>{String(item.feedback_type)} · {String(item.target_type)} · {String(item.status)}</span></div><div className="admin-row-buttons"><button title="开始核验" onClick={() => void reviewFeedback(String(item.feedback_id), 'reviewing')}><Eye size={14} /></button><button title="标记已解决" onClick={() => void reviewFeedback(String(item.feedback_id), 'resolved')}><Check size={14} /></button></div></div>) : <div className="admin-empty">暂无用户纠错</div>}</section>
    <section className="admin-panel"><div className="admin-panel-title"><h2>内容发现</h2><span>{content.length} 篇</span></div><form className="admin-inline-form" onSubmit={saveContent}><input required placeholder="标题" value={contentTitle} onChange={(e) => setContentTitle(e.target.value)} /><input required placeholder="摘要 / 来源说明" value={contentSummary} onChange={(e) => setContentSummary(e.target.value)} /><button title="发布指南"><Plus size={15} /></button></form>{content.length ? content.slice(0, 20).map((item) => <div className="admin-row" key={String(item.content_id)}><div><strong>{String(item.title)}</strong><span>{String(item.category)} · {String(item.status)}</span></div><button className="admin-icon-button" title="删除内容" onClick={() => void deleteContent(String(item.content_id))}><Trash2 size={14} /></button></div>) : <div className="admin-empty">还没有发布内容</div>}</section>
    <section className="admin-panel"><div className="admin-panel-title"><h2>客服工单</h2><span>{tickets.filter((item) => !['resolved', 'closed'].includes(String(item.status))).length} 条待处理</span></div>{tickets.length ? tickets.map((item) => <div className="admin-row" key={String(item.ticket_id)}><div><strong>{String(item.subject)}</strong><span>{String(item.category)} · {String(item.status)} · 用户 {String(item.user_id)}</span></div><div className="admin-row-buttons"><button title="回复并等待用户" onClick={() => void replyTicket(String(item.ticket_id), 'waiting_user')}><Eye size={14} /></button><button title="回复并解决" onClick={() => void replyTicket(String(item.ticket_id), 'resolved')}><Check size={14} /></button></div></div>) : <div className="admin-empty">暂无客服工单</div>}</section>
    <div className="admin-grid"><section className="admin-panel"><div className="admin-panel-title"><h2>用户与访问控制</h2><span>{users.length} 个账户</span></div>{users.map((item) => <div className="admin-row" key={String(item.user_id)}><div><strong>{String(item.display_name)}</strong><span>{String(item.email)} · {String(item.status)} · {item.email_verified ? '邮箱已验证' : '邮箱未验证'}</span></div><button title={item.status === 'active' ? '停用并退出全部设备' : '恢复账户'} onClick={() => void updateUser(String(item.user_id), item.status === 'active' ? 'suspended' : 'active')}>{item.status === 'active' ? <Pause size={14} /> : <Play size={14} />}</button></div>)}</section><section className="admin-panel"><div className="admin-panel-title"><h2>会员开通候补</h2><span>{upgrades.filter((item) => item.status === 'pending').length} 条待联系</span></div>{upgrades.length ? upgrades.map((item) => <div className="admin-row" key={String(item.request_id)}><div><strong>{String(item.display_name || item.email)}</strong><span>{String(item.plan_code)} · {String(item.status)}</span></div><div className="admin-row-buttons"><button title="标记已联系" onClick={() => void updateUpgrade(String(item.request_id), 'contacted')}><Check size={14} /></button><button title="拒绝申请" onClick={() => void updateUpgrade(String(item.request_id), 'rejected')}><Trash2 size={14} /></button></div></div>) : <div className="admin-empty">暂无升级申请</div>}</section></div>
    <div className="admin-grid"><section className="admin-panel"><div className="admin-panel-title"><h2>活动与推荐位</h2><span>{campaigns.length} 个活动</span></div><form className="admin-inline-form" onSubmit={saveCampaign}><input required placeholder="活动标题" value={campaignTitle} onChange={(e) => setCampaignTitle(e.target.value)} /><input required placeholder="活动摘要" value={campaignSummary} onChange={(e) => setCampaignSummary(e.target.value)} /><button title="发布到发现页"><Plus size={15} /></button></form>{campaigns.map((item) => <div className="admin-row" key={String(item.campaign_id)}><div><strong>{String(item.title)}</strong><span>{String(item.placement)} · {String(item.status)}</span></div><button title="删除活动" onClick={() => void deleteCampaign(String(item.campaign_id))}><Trash2 size={14} /></button></div>)}</section><section className="admin-panel"><div className="admin-panel-title"><h2>商品风控规则</h2><span>{riskRules.filter((item) => item.enabled).length} 条启用</span></div><form className="admin-inline-form" onSubmit={saveRiskRule}><input required placeholder="规则名称" value={riskName} onChange={(e) => setRiskName(e.target.value)} /><input required placeholder="标题风险词" value={riskPattern} onChange={(e) => setRiskPattern(e.target.value)} /><button title="新增风控规则"><Plus size={15} /></button></form>{riskRules.map((item) => <div className="admin-row" key={String(item.rule_id)}><div><strong>{String(item.name)}</strong><span>{String(item.field_name)} 包含“{String(item.pattern)}” · {String(item.severity)}</span></div><button title="删除规则" onClick={() => void deleteRiskRule(String(item.rule_id))}><Trash2 size={14} /></button></div>)}</section></div>
    <div className="admin-grid"><section className="admin-panel"><div className="admin-panel-title"><h2>公开分享治理</h2><span>{shares.filter((item) => item.status === 'active').length} 条有效</span></div>{shares.slice(0, 30).map((item) => <div className="admin-row" key={String(item.share_id)}><div><strong>{String(item.title)}</strong><span>{String(item.share_type)} · {String(item.status)} · 用户 {String(item.user_id)}</span></div>{item.status === 'active' && <button title="撤销公开分享" onClick={() => void revokeShare(String(item.share_id))}><Trash2 size={14} /></button>}</div>)}</section><section className="admin-panel"><div className="admin-panel-title"><h2>管理员审计日志</h2><span>最近 {audits.length} 条</span></div>{audits.slice(0, 30).map((item) => <div className="admin-row" key={String(item.audit_id)}><div><strong>{String(item.action)}</strong><span>{String(item.target_type)} · {String(item.target_id || '')} · 操作者 {String(item.actor_id)}</span></div><b>{String(item.created_at).slice(0, 16)}</b></div>)}</section></div>
    <section className="admin-panel"><div className="admin-panel-title"><h2>产品实验</h2><span>{experiments.filter((item) => item.status === 'running').length} 个运行中</span></div><form className="admin-inline-form" onSubmit={saveExperiment}><input required placeholder="实验编码" value={experimentCode} onChange={(e) => setExperimentCode(e.target.value)} /><input required placeholder="实验名称" value={experimentName} onChange={(e) => setExperimentName(e.target.value)} /><button title="启动 control / compact 实验"><Plus size={15} /></button></form>{experiments.map((item) => <div className="admin-row" key={String(item.experiment_id)}><div><strong>{String(item.name)}</strong><span>{String(item.code)} · {String(item.status)} · {Array.isArray(item.variants) ? item.variants.join(' / ') : ''}</span></div></div>)}</section>
    <section className="admin-panel"><div className="admin-panel-title"><h2>业务结果指标</h2><span>最近 30 天</span></div><div className="admin-kpis"><article><span>分析完成率</span><strong>{`${Math.round(Number(metrics.analysis_completion_rate || 0) * 100)}%`}</strong></article><article><span>建议采纳率</span><strong>{`${Math.round(Number(metrics.recommendation_acceptance_rate || 0) * 100)}%`}</strong></article><article><span>实际节省</span><strong>¥{Number(metrics.actual_savings || 0).toFixed(0)}</strong></article><article><span>分析 P95</span><strong>{String(metrics.analysis_p95_latency_ms || 0)}ms</strong></article></div></section>
  </section>;
}
