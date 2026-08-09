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

  async function load() {
    setError('');
    try {
      const [catalog, promptData, benchmarkData, monitorData, feedbackData, metricsData, contentData] = await Promise.all([
        api<{ products: Item[] }>('/api/v1/admin/catalog/products'),
        api<{ prompts: Item[] }>('/api/v1/admin/prompts'),
        api<{ runs: Item[] }>('/api/v1/admin/benchmarks'),
        api<{ monitors: Item[] }>('/api/v1/admin/monitors'),
        api<{ feedback: Item[] }>('/api/v1/admin/feedback'),
        api<Record<string, unknown>>('/api/v1/admin/metrics'),
        api<{ items: Item[] }>('/api/v1/admin/content'),
      ]);
      setProducts(catalog.products); setPrompts(promptData.prompts); setBenchmarks(benchmarkData.runs); setMonitors(monitorData.monitors);
      setFeedback(feedbackData.feedback);
      setMetrics(metricsData);
      setContent(contentData.items);
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
    <section className="admin-panel"><div className="admin-panel-title"><h2>业务结果指标</h2><span>最近 30 天</span></div><div className="admin-kpis"><article><span>分析完成率</span><strong>{`${Math.round(Number(metrics.analysis_completion_rate || 0) * 100)}%`}</strong></article><article><span>建议采纳率</span><strong>{`${Math.round(Number(metrics.recommendation_acceptance_rate || 0) * 100)}%`}</strong></article><article><span>实际节省</span><strong>¥{Number(metrics.actual_savings || 0).toFixed(0)}</strong></article><article><span>分析 P95</span><strong>{String(metrics.analysis_p95_latency_ms || 0)}ms</strong></article></div></section>
  </section>;
}
