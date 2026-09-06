import {
  ArrowUpRight,
  ChevronRight,
  ExternalLink,
  Laptop,
  Loader2,
  MessageSquare,
  Minus,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { MarkdownContent } from "./MarkdownContent";
import type { CommerceSearchResponse, ConsumerProduct } from "./ConsumerHub";

type CopilotMessage = {
  id: string;
  role: "user" | "assistant";
  createdAt: string;
  content: string;
  query?: string;
  response?: CommerceSearchResponse | null;
  loading?: boolean;
  error?: boolean;
};

type FollowUpSuggestion = {
  label: string;
  query: string;
  hint: string;
};

const QUICK_PROMPTS = [
  "只看官方店",
  "找更便宜替代款",
  "预算再降 20%",
  "更适合 MacBook",
  "看同款差异",
  "继续追问",
];

const PROVIDER_LABELS: Record<string, string> = {
  jd: "京东",
  taobao: "淘宝",
  tb: "淘宝",
  pdd: "拼多多",
  douyin: "抖音",
  vip: "唯品会",
};

const SOURCE_KIND_LABELS: Record<string, string> = {
  official_affiliate: "官方/联盟",
  affiliate: "联盟",
  official_api: "官方 API",
  public_page: "公开页面",
  browser_extension: "浏览器扩展",
  manual_input: "手动补充",
};

const money = (value?: number) => `¥${Number(value || 0).toFixed(0)}`;

function threadStorageKey(owner: string) {
  return `valuesee-copilot-thread:${owner || "guest"}`;
}

function finalPrice(product: ConsumerProduct) {
  return Math.max(
    0,
    product.price -
      product.coupon -
      product.platform_discount -
      product.member_discount -
      product.subsidy -
      product.pay_discount +
      product.shipping -
      product.gift_value,
  );
}

function sourceLabel(provider: string) {
  return PROVIDER_LABELS[provider.toLowerCase()] || provider.toUpperCase() || "来源";
}

function kindLabel(kind: string) {
  return SOURCE_KIND_LABELS[kind] || kind || "公开来源";
}

function createWelcomeMessage(): CopilotMessage {
  return {
    id: `welcome-${Date.now()}`,
    role: "assistant",
    createdAt: new Date().toISOString(),
    content:
      "欢迎来到 ValuSee AI 导购。你可以直接说需求，比如“给我找一台适合写代码的 27 寸显示器，预算 2500”。我会把可追溯来源、候选商品、到手价和下一步追问一起整理出来。",
  };
}

function buildSummary(query: string, response: CommerceSearchResponse) {
  const okSources = response.sources.filter((item) => item.status === "ok");
  const sourceText = response.sources.length
    ? response.sources
        .map((item) =>
          `${sourceLabel(item.provider)} · ${item.status === "ok" ? `${item.count || 0} 条` : item.error || "暂不可用"}`,
        )
        .join(" / ")
    : "暂无可追溯来源";
  return `### 我先帮你搜了一轮

- 关键词：${query}
- 找到候选：${response.results.length} 个
- 来源状态：${sourceText}
- 可用来源：${okSources.length} 个

${response.message}

接下来可以继续追问：
- 官方店优先
- 更便宜替代
- 预算再降 20%
- 设备兼容`;
}

function buildSearchFallback(query: string) {
  return `### 暂时没有找到可展示的授权结果

- 关键词：${query}
- 说明：当前没有可用的授权平台商品来源，或本次查询条件不足以返回结果。

你可以继续追问：
- 换一个更具体的型号
- 官方店优先
- 改成截图录入
- 用浏览器扩展采集当前页面`;
}

function collapsePreview(content: string, limit = 118) {
  const trimmed = content.replace(/\s+/g, " ").trim();
  return trimmed.length > limit ? `${trimmed.slice(0, limit)}...` : trimmed;
}

function buildFollowUpSuggestions(baseQuery: string, response?: CommerceSearchResponse | null): FollowUpSuggestion[] {
  const topic = baseQuery.trim() || "这件商品";
  const suggestions: FollowUpSuggestion[] = [
    { label: "只看官方店", query: `${topic} 只看官方店`, hint: "优先核验店铺资质和售后" },
    { label: "换更便宜替代", query: `${topic} 更便宜 替代款`, hint: "找更低到手价方案" },
    { label: "追问售后", query: `${topic} 保修 退货 价保`, hint: "补充保修与退货边界" },
    { label: "比同款不同版", query: `${topic} 同款 不同版本`, hint: "避免误比不同 SKU" },
  ];
  if (!response?.results.length) return suggestions;
  return [
    ...suggestions,
    { label: "继续深挖评论", query: `${topic} 评论 缺点`, hint: "看高频差评和常见故障" },
    { label: "重算到手价", query: `${topic} 到手价 优惠`, hint: "重新核对券、补贴和运费" },
  ];
}

function sourceHealthText(status: string) {
  if (status === "ok") return "可用";
  if (status === "empty") return "无结果";
  return "需确认";
}

export function ShoppingCopilotPage({
  draftOwner,
  candidateCount,
  signedIn,
  onSearch,
  onAddCandidate,
  onOpenProduct,
  onOpenAnalyze,
}: {
  draftOwner: string;
  candidateCount: number;
  signedIn: boolean;
  onSearch: (query: string) => Promise<CommerceSearchResponse>;
  onAddCandidate: (product: ConsumerProduct) => void;
  onOpenProduct: (product: ConsumerProduct) => void;
  onOpenAnalyze: () => void;
}) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [collapsedMessages, setCollapsedMessages] = useState<Record<string, boolean>>({});
  const [messages, setMessages] = useState<CopilotMessage[]>(() => {
    try {
      const raw = localStorage.getItem(threadStorageKey(draftOwner));
      if (!raw) return [createWelcomeMessage()];
      const parsed = JSON.parse(raw) as CopilotMessage[];
      return Array.isArray(parsed) && parsed.length ? parsed : [createWelcomeMessage()];
    } catch {
      return [createWelcomeMessage()];
    }
  });
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(threadStorageKey(draftOwner));
      if (!raw) {
        setMessages([createWelcomeMessage()]);
        return;
      }
      const parsed = JSON.parse(raw) as CopilotMessage[];
      setMessages(Array.isArray(parsed) && parsed.length ? parsed : [createWelcomeMessage()]);
    } catch {
      setMessages([createWelcomeMessage()]);
    }
  }, [draftOwner]);

  useEffect(() => {
    try {
      localStorage.setItem(threadStorageKey(draftOwner), JSON.stringify(messages.slice(-30)));
    } catch {
      /* localStorage may be unavailable in hardened contexts. */
    }
  }, [draftOwner, messages]);

  useEffect(() => {
    const container = listRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }, [messages, loading]);

  const lastQuery = useMemo(() => {
    const last = [...messages].reverse().find((item) => item.role === "user" && item.query?.trim());
    return last?.query?.trim() || "";
  }, [messages]);

  const latestResponse = useMemo(
    () => [...messages].reverse().find((item) => item.response)?.response || null,
    [messages],
  );
  const latestResults = latestResponse?.results || [];
  const followUps = useMemo(() => buildFollowUpSuggestions(lastQuery, latestResponse), [lastQuery, latestResponse]);

  async function submitSearch(query: string) {
    const keyword = query.trim();
    if (!keyword || loading) return;
    setLoading(true);
    setInput("");
    const userMessage: CopilotMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      createdAt: new Date().toISOString(),
      content: keyword,
      query: keyword,
    };
    const placeholderId = `assistant-${Date.now()}`;
    setMessages((items) => [
      ...items,
      userMessage,
      {
        id: placeholderId,
        role: "assistant",
        createdAt: new Date().toISOString(),
        content: "正在搜索可追溯来源商品，并整理候选、价格和下一步追问...",
        loading: true,
      },
    ]);
    try {
      const response = await onSearch(keyword);
      setMessages((items) =>
        items.map((item) =>
          item.id === placeholderId
            ? {
                ...item,
                loading: false,
                response,
                content: response.results.length ? buildSummary(keyword, response) : buildSearchFallback(keyword),
              }
            : item,
        ),
      );
    } catch (error) {
      const content = error instanceof Error ? error.message : "搜索失败，请稍后再试";
      setMessages((items) =>
        items.map((item) =>
          item.id === placeholderId
            ? {
                ...item,
                loading: false,
                error: true,
                content,
              }
            : item,
        ),
      );
    } finally {
      setLoading(false);
    }
  }

  function runQuickPrompt(prompt: string) {
    const base = lastQuery || input.trim() || "我想买一件商品";
    void submitSearch(prompt === "继续追问" ? base : `${base} ${prompt}`.trim());
  }

  function runMessageSearch(query: string) {
    void submitSearch(query);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void submitSearch(input);
  }

  return (
    <section className="copilot-page">
      <header className="copilot-head">
        <div>
          <span className="section-kicker">AI 导购工作台</span>
          <h1>像专业导购一样追问购物需求</h1>
          <p>说出预算、用途和顾虑，ValuSee 会搜索可追溯来源，整理候选商品、价格依据、风险线索和可以继续追问的问题。</p>
        </div>
        <div className="copilot-head-card">
          <article>
            <strong>{candidateCount}</strong>
            <span>候选商品</span>
          </article>
          <article>
            <strong>{signedIn ? "已登录" : "待登录"}</strong>
            <span>搜索身份</span>
          </article>
          <article>
            <strong>{messages.filter((item) => item.role === "user").length}</strong>
            <span>追问轮次</span>
          </article>
        </div>
      </header>

      <div className="copilot-layout">
        <section className="copilot-stream panel">
          <div className="copilot-stream-head">
            <div>
              <span>对话</span>
              <h2>把购物需求直接丢给 AI</h2>
            </div>
            <button type="button" className="soft-button" onClick={onOpenAnalyze} disabled={!candidateCount}>
              <Sparkles size={16} />
              去对比工作台
            </button>
          </div>

          <div className="copilot-list" ref={listRef}>
            {messages.map((message) => {
              const canCollapse = message.role === "assistant" && !message.loading;
              const collapsed = Boolean(collapsedMessages[message.id]);
              return (
                <article
                  key={message.id}
                  className={`copilot-message ${message.role}${message.error ? " is-error" : ""}${message.loading ? " is-loading" : ""}${collapsed ? " is-collapsed" : ""}`}
                >
                  <div className="copilot-message-topline">
                    <div className="copilot-message-badge">
                      {message.role === "user" ? <MessageSquare size={14} /> : <Sparkles size={14} />}
                      <span>{message.role === "user" ? "我" : "ValuSee"}</span>
                    </div>
                    {canCollapse && (
                      <button
                        type="button"
                        className="copilot-collapse"
                        onClick={() => setCollapsedMessages((items) => ({ ...items, [message.id]: !items[message.id] }))}
                      >
                        {collapsed ? <Plus size={14} /> : <Minus size={14} />}
                        {collapsed ? "展开" : "收起"}
                      </button>
                    )}
                  </div>
                  <div className="copilot-message-body">
                    {collapsed ? (
                      <p className="copilot-preview">{collapsePreview(message.content)}</p>
                    ) : message.role === "assistant" ? (
                      <MarkdownContent className="copilot-markdown">{message.content}</MarkdownContent>
                    ) : (
                      <p>{message.content}</p>
                    )}

                    {!collapsed && message.response && (
                      <>
                        <div className="copilot-source-strip" aria-label="消息来源">
                          {message.response.sources.map((source) => (
                            <span
                              key={`${message.id}-${source.provider}-${source.status}`}
                              className={`copilot-source ${source.status === "ok" ? "ok" : "error"}`}
                            >
                              {sourceLabel(source.provider)} · {source.status === "ok" ? `${source.count || 0} 条` : source.error || "暂不可用"}
                            </span>
                          ))}
                        </div>
                        {message.response.results.length ? (
                          <div className="copilot-results">
                            {message.response.results.map((result) => {
                              const product = result.product;
                              return (
                                <article key={`${result.provider}-${product.url}-${product.sku}`} className="copilot-result-card">
                                  <div className="copilot-result-visual">
                                    {product.image_url ? (
                                      <img src={product.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" />
                                    ) : (
                                      <Laptop size={28} />
                                    )}
                                  </div>
                                  <div className="copilot-result-copy">
                                    <span>
                                      {sourceLabel(result.provider)} · {kindLabel(result.kind)}
                                    </span>
                                    <h3>{product.title}</h3>
                                    <p>
                                      {product.store_name || product.platform || "来源待确认"} · {product.model || product.sku || "规格待确认"}
                                    </p>
                                    <strong>{money(finalPrice(product))}</strong>
                                    <small>
                                      页面价 {money(product.price)} · 优惠{" "}
                                      {money(
                                        product.coupon +
                                          product.platform_discount +
                                          product.member_discount +
                                          product.subsidy +
                                          product.pay_discount,
                                      )}
                                    </small>
                                  </div>
                                  <div className="copilot-result-actions">
                                    <button type="button" onClick={() => onAddCandidate(product)}>
                                      <Plus size={14} />
                                      加入对比
                                    </button>
                                    {product.url && (
                                      <a href={product.url} target="_blank" rel="noreferrer">
                                        <ExternalLink size={14} />
                                        查看来源
                                      </a>
                                    )}
                                    <button type="button" onClick={() => onOpenProduct(product)}>
                                      <ArrowUpRight size={14} />
                                      看详情
                                    </button>
                                  </div>
                                </article>
                              );
                            })}
                          </div>
                        ) : (
                          <div className="copilot-empty-results">
                            <ShieldCheck size={16} />
                            <span>当前没有可展示的授权商品结果。你可以换个关键词继续追问，或改用截图和浏览器扩展采集页面信息。</span>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </article>
              );
            })}

            {loading && (
              <article className="copilot-message assistant is-loading">
                <div className="copilot-message-badge">
                  <Sparkles size={14} />
                  <span>ValuSee</span>
                </div>
                <div className="copilot-message-body">
                  <p>正在搜索可追溯来源商品...</p>
                  <div className="copilot-loading">
                    <Loader2 size={16} className="spin" />
                    <span>整理消息来源、价格和候选列表</span>
                  </div>
                </div>
              </article>
            )}
          </div>

          <form className="copilot-composer" onSubmit={handleSubmit}>
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="例如：给我找一台适合代码办公的 27 英寸显示器，预算 2500 元"
              rows={3}
            />
            <div className="copilot-composer-bar">
              <div className="copilot-pills">
                {QUICK_PROMPTS.map((item) => (
                  <button type="button" key={item} onClick={() => runQuickPrompt(item)}>
                    {item}
                  </button>
                ))}
              </div>
              <button type="submit" disabled={loading || !input.trim()}>
                {loading ? <Loader2 className="spin" size={16} /> : <Search size={16} />}
                发送
              </button>
            </div>
          </form>
        </section>

        <aside className="copilot-sidebar">
          <section className="copilot-card copilot-source-board">
            <span>来源面板</span>
            <h2>{latestResponse?.sources.length ? "本轮搜索来源" : "等待搜索"}</h2>
            <div className="copilot-source-cards">
              {(latestResponse?.sources || []).map((source) => (
                <article key={`${source.provider}-${source.status}`}>
                  <b>{sourceLabel(source.provider)}</b>
                  <strong>{source.status === "ok" ? `${source.count || 0} 条` : sourceHealthText(source.status)}</strong>
                  <small>{source.status === "ok" ? "已返回可展示结果" : source.error || "需要换关键词或补充信息"}</small>
                </article>
              ))}
              {!latestResponse?.sources.length && (
                <div className="copilot-sidebar-empty">
                  <ShieldCheck size={16} />
                  <p>搜索后会在这里展示每个平台的可用状态和证据来源。</p>
                </div>
              )}
            </div>
          </section>

          <section className="copilot-card copilot-followup-board">
            <span>追问队列</span>
            <h2>{lastQuery ? "下一步可以这样问" : "先发一句需求"}</h2>
            <div className="copilot-followup-list">
              {followUps.map((item) => (
                <button type="button" key={item.label} onClick={() => runMessageSearch(item.query)}>
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.hint}</small>
                  </span>
                  <ChevronRight size={14} />
                </button>
              ))}
            </div>
          </section>

          <section className="copilot-card copilot-evidence-board">
            <span>候选证据</span>
            <h2>{latestResults.length ? `${latestResults.length} 个商品可处理` : "暂无候选"}</h2>
            <div className="copilot-mini-products">
              {latestResults.slice(0, 4).map((result) => {
                const product = result.product;
                return (
                  <article key={`${result.provider}-${product.url}-${product.sku}`}>
                    <div className="copilot-mini-thumb">
                      {product.image_url ? <img src={product.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" /> : <Laptop size={18} />}
                    </div>
                    <div>
                      <strong>{product.title}</strong>
                      <span>
                        {sourceLabel(result.provider)} · {money(finalPrice(product))}
                      </span>
                    </div>
                    <button type="button" title="加入对比" onClick={() => onAddCandidate(product)}>
                      <Plus size={14} />
                    </button>
                  </article>
                );
              })}
              {!latestResults.length && <p>有授权结果后，会在这里沉淀成候选卡片，可一键加入对比。</p>}
            </div>
          </section>

          <section className="copilot-card">
            <span>工作流入口</span>
            <h2>{candidateCount ? `${candidateCount} 个候选已可对比` : "还没有候选商品"}</h2>
            <p>{candidateCount ? "可以进入对比工作台继续做规格、风险和到手价核验。" : "先搜索、加入对比，再进入深度分析。"}</p>
            <div className="copilot-sidebar-actions">
              <button type="button" onClick={onOpenAnalyze} disabled={!candidateCount}>
                <Sparkles size={16} />
                去对比工作台
              </button>
              <button type="button" onClick={() => runMessageSearch(lastQuery || "适合代码办公的显示器")}>
                <Search size={16} />
                继续追问
              </button>
            </div>
            <div className="copilot-mini-note">
              <ShieldCheck size={16} />
              <span>搜索结果来自授权来源或用户确认的信息。下单前仍需回到原平台核验当前 SKU、库存和最终价格。</span>
            </div>
          </section>
        </aside>
      </div>
    </section>
  );
}
