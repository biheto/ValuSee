import { Activity, BarChart3, Bot, Database, ExternalLink, RefreshCw, Server, ShieldCheck, ShoppingBag, Timer, Workflow } from 'lucide-react';
import { FormEvent, useEffect, useState } from 'react';

type Overview = {
  health: Record<string, number>;
  tasks: Array<Record<string, unknown>>;
  monitors: Array<Record<string, unknown>>;
  traces: Array<Record<string, unknown>>;
  benchmarks: Array<Record<string, unknown>>;
  llm_usage: Record<string, unknown>;
  mcp: Record<string, unknown>;
  commerce_providers: Array<Record<string, unknown>>;
};

async function adminRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = localStorage.getItem('valuesee-token');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(String(body.detail ?? `请求失败：${response.status}`));
  return body as T;
}

export function AdminConsole() {
  const [data, setData] = useState<Overview | null>(null);
  const [tab, setTab] = useState<'overview' | 'tasks' | 'traces' | 'sources'>('overview');
  const [error, setError] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loggingIn, setLoggingIn] = useState(false);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true); setError('');
    try { setData(await adminRequest<Overview>('/api/v1/admin/overview')); }
    catch (err) { setError(err instanceof Error ? err.message : '管理端加载失败'); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);

  async function login(event: FormEvent) {
    event.preventDefault(); setLoggingIn(true); setError('');
    try {
      const result = await adminRequest<{ access_token: string }>('/api/v1/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
      localStorage.setItem('valuesee-token', result.access_token); await load();
    } catch (err) { setError(err instanceof Error ? err.message : '登录失败'); }
    finally { setLoggingIn(false); }
  }

  if (!data) return <main className="admin-app"><div className="admin-login"><div className="admin-logo"><ShieldCheck size={19} /> ValuSee Admin</div><h1>管理端登录</h1><p>查看商品来源、Agent 任务、模型调用和运行状态。</p><form onSubmit={login}><input type="email" required placeholder="管理员邮箱" value={email} onChange={(event) => setEmail(event.target.value)} /><input type="password" required placeholder="密码" value={password} onChange={(event) => setPassword(event.target.value)} /><button className="admin-primary" disabled={loggingIn}>{loggingIn ? '登录中…' : '进入管理端'}</button></form>{error && <div className="admin-error">{error}</div>}<a className="admin-back" href="/">返回用户端</a></div></main>;

  const tabs = [['overview', '总览', BarChart3], ['tasks', 'Agent 任务', Workflow], ['traces', 'LLM Trace', Activity], ['sources', '商品来源', ShoppingBag]] as const;
  return <main className="admin-app"><header className="admin-header"><div><div className="admin-logo"><ShieldCheck size={19} /> ValuSee Admin</div><h1>运营与 Agent 控制台</h1><p>商品来源、决策任务、模型调用和系统健康状态集中管理。</p></div><div className="admin-header-actions"><button className="admin-icon-button" title="刷新数据" onClick={() => void load()}><RefreshCw size={17} className={loading ? 'spin' : ''} /></button><a href="/" className="admin-back">用户端</a></div></header><nav className="admin-tabs">{tabs.map(([key, label, Icon]) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}><Icon size={16} />{label}</button>)}</nav>{error && <div className="admin-error">{error}</div>}{tab === 'overview' && <OverviewTab data={data} />}{tab === 'tasks' && <TaskTab tasks={data.tasks} />}{tab === 'traces' && <TraceTab traces={data.traces} usage={data.llm_usage} />}{tab === 'sources' && <SourceTab providers={data.commerce_providers} mcp={data.mcp} />}</main>;
}

function OverviewTab({ data }: { data: Overview }) {
  const cards = [['任务总数', data.health.tasks, Workflow], ['运行中', data.health.running_tasks, Timer], ['价格监控', data.health.active_monitors, ShoppingBag], ['LLM Trace', data.health.traces, Activity]] as const;
  return <section className="admin-content"><div className="admin-kpis">{cards.map(([label, value, Icon]) => <article key={label}><Icon size={19} /><span>{label}</span><strong>{value}</strong></article>)}</div><div className="admin-grid"><section className="admin-panel"><div className="admin-panel-title"><h2>最近 Agent 任务</h2><span>可追溯执行结果</span></div>{data.tasks.length ? data.tasks.slice(0, 8).map((task) => <div className="admin-row" key={String(task.task_id)}><div><strong>{String(task.goal ?? task.task_id)}</strong><span>{String(task.execution_mode ?? 'shopping')} · {String(task.status ?? 'unknown')}</span></div><b>{String(task.updated_at ?? task.created_at ?? '')}</b></div>) : <EmptyAdmin text="暂无任务记录" />}</section><section className="admin-panel"><div className="admin-panel-title"><h2>系统依赖</h2><span>生产环境健康检查</span></div><div className="dependency-list"><div><Database size={17} /><span>数据库</span><b className="status-ok">在线</b></div><div><Server size={17} /><span>消息与缓存</span><b className="status-ok">已配置</b></div><div><Bot size={17} /><span>MCP Provider</span><b>{String((data.mcp as { provider?: string }).provider ?? 'local')}</b></div></div></section></div></section>;
}

function TaskTab({ tasks }: { tasks: Array<Record<string, unknown>> }) { return <section className="admin-content"><section className="admin-panel"><div className="admin-panel-title"><h2>Agent 执行任务</h2><span>{tasks.length} 条</span></div>{tasks.length ? tasks.map((task) => <div className="admin-row" key={String(task.task_id)}><div><strong>{String(task.goal ?? task.task_id)}</strong><span>模式：{String(task.execution_mode ?? 'unknown')} · 状态：{String(task.status ?? 'unknown')}</span></div><b>{String(task.created_at ?? '')}</b></div>) : <EmptyAdmin text="暂无 Agent 任务" />}</section></section>; }
function TraceTab({ traces, usage }: { traces: Array<Record<string, unknown>>; usage: Record<string, unknown> }) { return <section className="admin-content"><section className="admin-panel"><div className="admin-panel-title"><h2>LLM 调用 Trace</h2><span>用量：{String(usage.total_tokens ?? 0)} tokens</span></div>{traces.length ? traces.map((trace, index) => <div className="admin-row" key={String(trace.trace_id ?? index)}><div><strong>{String(trace.agent ?? 'unknown agent')}</strong><span>{String(trace.model ?? 'fallback')} · 输入 {String(trace.input_tokens ?? 0)} · 输出 {String(trace.output_tokens ?? 0)}</span></div><b>{String(trace.latency_ms ?? 0)} ms</b></div>) : <EmptyAdmin text="暂无模型调用记录" />}</section></section>; }
function SourceTab({ providers, mcp }: { providers: Array<Record<string, unknown>>; mcp: Record<string, unknown> }) { return <section className="admin-content"><div className="admin-grid"><section className="admin-panel"><div className="admin-panel-title"><h2>商品数据来源</h2><span>授权后才会返回真实商品</span></div>{providers.length ? providers.map((item) => <div className="admin-row" key={String(item.name)}><div><strong>{String(item.name)}</strong><span>{String(item.kind ?? 'official_or_affiliate')}</span></div><b className="status-ok">已配置</b></div>) : <EmptyAdmin text="尚未配置平台适配器" />}</section><section className="admin-panel"><div className="admin-panel-title"><h2>MCP 状态</h2><span>工具调用安全边界</span></div><div className="dependency-list"><div><Bot size={17} /><span>Provider</span><b>{String(mcp.provider ?? 'local')}</b></div><div><Server size={17} /><span>状态</span><b className="status-ok">{String(mcp.status ?? 'ready')}</b></div></div><a className="admin-doc-link" href="/docs" target="_blank" rel="noreferrer"><ExternalLink size={14} />查看接口文档</a></section></div></section>; }
function EmptyAdmin({ text }: { text: string }) { return <div className="admin-empty">{text}</div>; }
