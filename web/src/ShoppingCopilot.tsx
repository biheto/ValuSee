import {
  ArrowLeft,
  ArrowUpRight,
  Bot,
  BrainCircuit,
  ChevronRight,
  Clock3,
  Database,
  ExternalLink,
  History,
  Laptop,
  Loader2,
  MessageSquare,
  Minus,
  PanelLeft,
  Plus,
  PlugZap,
  SearchCode,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UserRound,
  Wrench,
  X,
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
  mode?: CopilotMode;
  response?: CommerceSearchResponse | null;
  loading?: boolean;
  error?: boolean;
};

type FollowUpSuggestion = {
  label: string;
  query: string;
  hint: string;
};

type CopilotMode = "guide" | "research" | "compare" | "deal";
type CapabilityKind = "rag" | "skill" | "mcp";
type CapabilityItem = {
  id: string;
  name: string;
  detail: string;
  status?: string;
  contents: Array<{ label: string; description: string }>;
  definitions: Array<{ term: string; meaning: string }>;
  input: string;
  output: string;
  trust: string;
};

type CopilotPanel = "mode" | "capabilities" | "sources" | "followups" | "evidence" | "search" | null;
type CopilotThread = { id: string; title: string; preview: string; updatedAt: string };

const COPILOT_MODES = [
  { key: "guide", label: "导购模式", title: "像顾问一样追问", hint: "预算、用途、人群偏好", icon: Sparkles },
  { key: "research", label: "研究模式", title: "先查资料再回答", hint: "RAG 知识库优先", icon: BrainCircuit },
  { key: "compare", label: "对比模式", title: "按参数和风险拆解", hint: "SKU、价格、售后", icon: SlidersHorizontal },
  { key: "deal", label: "省钱模式", title: "寻找优惠和替代", hint: "券、补贴、历史价", icon: Search },
] as const;

const RAG_KNOWLEDGE_BASES: CapabilityItem[] = [
  {
    id: "product-sku",
    name: "商品与 SKU 知识库",
    detail: "型号、版本、规格差异",
    status: "已接入",
    contents: [
      { label: "型号归一", description: "把标题里的别名、后缀和套装信息整理成可比型号。" },
      { label: "SKU 差异", description: "识别容量、颜色、地区版、套装和保修版本差异。" },
      { label: "规格抽取", description: "沉淀屏幕、芯片、接口、尺寸等关键参数。" },
    ],
    definitions: [
      { term: "product_ref", meaning: "同一商品在 ValuSee 内部的聚合标识。" },
      { term: "sku_signature", meaning: "用于判断同款的品牌、型号、规格组合。" },
      { term: "variant_delta", meaning: "候选之间仍需用户确认的版本差异。" },
    ],
    input: "商品标题、型号、平台 SKU、用户粘贴的链接或截图文本",
    output: "同款/非同款判断、版本差异、关键规格字段",
    trust: "优先使用结构化商品字段；不确定时会提示用户回到源平台核验 SKU。",
  },
  {
    id: "price-promo",
    name: "价格与优惠证据库",
    detail: "到手价、券、补贴、运费",
    status: "检索中",
    contents: [
      { label: "价格拆解", description: "区分页面价、券后价、支付优惠、补贴和运费。" },
      { label: "叠加判断", description: "标记哪些优惠可能不可叠加。" },
      { label: "时效提示", description: "展示价格采集时间和需要重新确认的部分。" },
    ],
    definitions: [
      { term: "final_price", meaning: "按当前证据计算出的参考到手价。" },
      { term: "discount_stack", meaning: "参与计算的优惠项列表和来源。" },
      { term: "price_confidence", meaning: "价格是否需要回到源平台二次确认。" },
    ],
    input: "平台价、优惠券、会员折扣、补贴、运费与礼品价值",
    output: "到手价拆解、优惠来源、是否需要二次确认",
    trust: "价格会随时间变动，展示为导购参考，最终价格以源平台结算页为准。",
  },
  {
    id: "after-sales-risk",
    name: "售后与风险规则库",
    detail: "退换、保修、平台风险",
    status: "已接入",
    contents: [
      { label: "售后边界", description: "识别退换、价保、保修和发票条件。" },
      { label: "平台风险", description: "提示店铺资质、非官方渠道和履约不确定性。" },
      { label: "用户偏好", description: "结合风险偏好调整提醒优先级。" },
    ],
    definitions: [
      { term: "risk_tag", meaning: "影响购买决策的风险标签。" },
      { term: "after_sales_scope", meaning: "售后服务覆盖范围和限制。" },
      { term: "evidence_source", meaning: "风险判断来自平台信息、规则库还是用户补充。" },
    ],
    input: "店铺类型、平台、商品类目、售后关键词和用户关注点",
    output: "保修/退换提醒、风险标签、建议追问项",
    trust: "风险规则来自本地策略与用户确认信息，不替代平台官方售后条款。",
  },
];

const COPILOT_SKILLS: CapabilityItem[] = [
  {
    id: "same-product",
    name: "同款识别",
    detail: "合并标题相似但 SKU 不同的商品",
    contents: [
      { label: "标题清洗", description: "移除营销词、赠品词和无关活动词。" },
      { label: "规格对齐", description: "对齐品牌、型号、容量、颜色和套装字段。" },
      { label: "差异保留", description: "对疑似不同版不强行合并，保留给用户确认。" },
    ],
    definitions: [
      { term: "same_product_score", meaning: "同款判断的相似度分值。" },
      { term: "mismatch_reason", meaning: "无法合并时的主要差异原因。" },
      { term: "manual_check", meaning: "需要用户或源平台确认的字段。" },
    ],
    input: "候选商品标题、品牌、型号、规格、来源链接",
    output: "同款候选、疑似不同版、需要人工确认的差异点",
    trust: "只在证据足够时合并；容量、颜色、套装和地区版差异会保留提醒。",
  },
  {
    id: "final-price",
    name: "到手价计算",
    detail: "拆分券、补贴、会员折扣与运费",
    contents: [
      { label: "优惠合并", description: "按同一口径合并券、满减、补贴和支付优惠。" },
      { label: "成本补全", description: "把运费、赠品价值、会员门槛纳入说明。" },
      { label: "异常提示", description: "发现价格缺项或优惠冲突时提示核验。" },
    ],
    definitions: [
      { term: "base_price", meaning: "商品页面展示的原始价格。" },
      { term: "deduction", meaning: "可解释的优惠抵扣金额。" },
      { term: "payable_price", meaning: "用户可能实际支付的参考金额。" },
    ],
    input: "原价、券、满减、平台补贴、支付优惠、运费、赠品价值",
    output: "统一口径的到手价与优惠明细",
    trust: "会把不确定优惠标出来，避免把不可叠加优惠直接相加。",
  },
  {
    id: "followup",
    name: "追问生成",
    detail: "发现缺失预算、用途和规格条件",
    contents: [
      { label: "缺口识别", description: "发现预算、用途、品牌偏好和设备条件缺失。" },
      { label: "下一问排序", description: "优先提出能改变购买结论的问题。" },
      { label: "上下文继承", description: "沿用上一轮需求和候选结果继续追问。" },
    ],
    definitions: [
      { term: "missing_signal", meaning: "当前决策缺失的关键信息。" },
      { term: "question_priority", meaning: "追问的重要程度和展示顺序。" },
      { term: "decision_impact", meaning: "回答后可能影响的筛选或排序结果。" },
    ],
    input: "用户当前问题、已选商品、缺失字段、历史追问",
    output: "下一步追问、筛选建议、需要补充的证据",
    trust: "追问只围绕购买决策缺口生成，避免无关聊天稀释判断。",
  },
];

const COPILOT_MCPS: CapabilityItem[] = [
  {
    id: "commerce-search",
    name: "Commerce Search",
    detail: "聚合授权商品来源",
    contents: [
      { label: "平台查询", description: "按关键词和模式请求可用商品来源。" },
      { label: "来源状态", description: "返回每个平台可用、无结果或错误原因。" },
      { label: "结果归一", description: "把不同平台字段整理为统一商品卡片。" },
    ],
    definitions: [
      { term: "provider", meaning: "商品来源平台或服务名称。" },
      { term: "source_url", meaning: "可跳回源平台核验的商品地址。" },
      { term: "fetch_status", meaning: "本次来源调用的状态。" },
    ],
    input: "用户搜索词、平台筛选条件、当前导购模式",
    output: "候选商品、来源状态、授权来源链接",
    trust: "只展示可追溯来源；不可用来源会在来源面板中标明。",
  },
  {
    id: "browser-capture",
    name: "Browser Capture",
    detail: "读取用户确认的页面采集",
    contents: [
      { label: "用户触发", description: "只处理用户主动上传或确认采集的数据。" },
      { label: "页面解析", description: "抽取标题、价格、图片、规格和来源链接。" },
      { label: "证据回填", description: "把采集结果同步到候选商品和对比工作台。" },
    ],
    definitions: [
      { term: "capture_id", meaning: "一次页面采集的记录编号。" },
      { term: "extracted_field", meaning: "从页面中识别出的结构化字段。" },
      { term: "user_confirmed", meaning: "是否已经由用户确认进入决策流程。" },
    ],
    input: "用户主动确认的页面、截图或扩展采集数据",
    output: "结构化商品字段、价格证据、源页面引用",
    trust: "不会静默读取页面；需要用户明确触发采集或上传。",
  },
  {
    id: "decision-workspace",
    name: "Decision Workspace",
    detail: "同步候选到智能对比工作台",
    contents: [
      { label: "候选同步", description: "把导购页选中的商品加入对比工作台。" },
      { label: "报告衔接", description: "把需求、证据和候选带入分析报告。" },
      { label: "草稿保留", description: "保留用户编辑后的购买决策草稿。" },
    ],
    definitions: [
      { term: "candidate", meaning: "用户明确加入对比的商品对象。" },
      { term: "decision_draft", meaning: "可继续编辑的需求和候选快照。" },
      { term: "analysis_entry", meaning: "从导购页跳转到智能对比的入口状态。" },
    ],
    input: "导购页选中的候选商品与用户需求",
    output: "对比候选、分析报告入口、可继续编辑的决策草稿",
    trust: "同步的是当前会话已确认候选，用户仍可在工作台删除或修正。",
  },
];

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

function threadStorageKey(owner: string, threadId?: string) {
  return `valuesee-copilot-thread:${owner || "guest"}${threadId ? `:${threadId}` : ""}`;
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

function modeLabel(mode?: CopilotMode) {
  return COPILOT_MODES.find((item) => item.key === mode)?.label || "AI 模式";
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

function capabilityKindLabel(kind: CapabilityKind) {
  if (kind === "rag") return "RAG 知识库";
  if (kind === "skill") return "Skill";
  return "MCP";
}

function findCapability(kind: CapabilityKind, id: string) {
  const source = kind === "rag" ? RAG_KNOWLEDGE_BASES : kind === "skill" ? COPILOT_SKILLS : COPILOT_MCPS;
  return source.find((item) => item.id === id) || null;
}

function CapabilityDetail({ item, kind }: { item: CapabilityItem; kind: CapabilityKind }) {
  return (
    <div className="copilot-capability-detail">
      <div className="copilot-capability-detail-head">
        <span>{capabilityKindLabel(kind)}</span>
        {item.status && <em>{item.status}</em>}
      </div>
      <h3>{item.name}</h3>
      <p>{item.detail}</p>
      <div className="copilot-capability-content-map">
        <strong>能力具体内容</strong>
        {item.contents.map((content) => (
          <article key={content.label}>
            <b>{content.label}</b>
            <small>{content.description}</small>
          </article>
        ))}
      </div>
      <div className="copilot-capability-definition-map">
        <strong>详细信息定义</strong>
        <dl>
          {item.definitions.map((definition) => (
            <div key={definition.term}>
              <dt>{definition.term}</dt>
              <dd>{definition.meaning}</dd>
            </div>
          ))}
        </dl>
      </div>
      <dl>
        <div>
          <dt>输入</dt>
          <dd>{item.input}</dd>
        </div>
        <div>
          <dt>输出</dt>
          <dd>{item.output}</dd>
        </div>
        <div>
          <dt>可信边界</dt>
          <dd>{item.trust}</dd>
        </div>
      </dl>
    </div>
  );
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
  const [mode, setMode] = useState<CopilotMode>("guide");
  const [activePanel, setActivePanel] = useState<CopilotPanel>(null);
  const [selectedCapability, setSelectedCapability] = useState<{ kind: CapabilityKind; id: string } | null>(null);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [panelSearch, setPanelSearch] = useState("");
  const [threadSearch, setThreadSearch] = useState("");
  const [threadId, setThreadId] = useState(() => `thread-${Date.now()}`);
  const [threads, setThreads] = useState<CopilotThread[]>([]);
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
      localStorage.setItem(threadStorageKey(draftOwner, threadId), JSON.stringify(messages.slice(-30)));
    } catch {
      /* localStorage may be unavailable in hardened contexts. */
    }
  }, [draftOwner, messages, threadId]);

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
  const activeMode = COPILOT_MODES.find((item) => item.key === mode) || COPILOT_MODES[0];
  const selectedCapabilityItem = selectedCapability ? findCapability(selectedCapability.kind, selectedCapability.id) : null;

  const currentThreadTitle = useMemo(() => {
    const firstQuery = messages.find((item) => item.role === "user")?.content?.trim();
    return firstQuery ? collapsePreview(firstQuery, 28) : "新的购物对话";
  }, [messages]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(`valuesee-copilot-threads:${draftOwner}`);
      const saved = raw ? JSON.parse(raw) as CopilotThread[] : [];
      setThreads(Array.isArray(saved) ? saved : []);
    } catch {
      setThreads([]);
    }
  }, [draftOwner]);

  useEffect(() => {
    const nextThread: CopilotThread = {
      id: threadId,
      title: currentThreadTitle,
      preview: collapsePreview(messages[messages.length - 1]?.content || "等待你的购物需求", 46),
      updatedAt: new Date().toISOString(),
    };
    setThreads((items) => {
      const next = [nextThread, ...items.filter((item) => item.id !== threadId)].slice(0, 20);
      try { localStorage.setItem(`valuesee-copilot-threads:${draftOwner}`, JSON.stringify(next)); } catch { /* storage is optional */ }
      return next;
    });
  }, [currentThreadTitle, draftOwner, messages, threadId]);

  const filteredThreads = threads.filter((item) => `${item.title} ${item.preview}`.toLowerCase().includes(threadSearch.trim().toLowerCase()));
  const panelItems = useMemo(() => {
    const keyword = panelSearch.trim().toLowerCase();
    const all = [
      ...RAG_KNOWLEDGE_BASES.map((item) => ({ kind: "rag" as CapabilityKind, item })),
      ...COPILOT_SKILLS.map((item) => ({ kind: "skill" as CapabilityKind, item })),
      ...COPILOT_MCPS.map((item) => ({ kind: "mcp" as CapabilityKind, item })),
    ];
    return all.filter(({ item }) => !keyword || `${item.name} ${item.detail} ${item.contents.map((entry) => entry.label).join(" ")}`.toLowerCase().includes(keyword));
  }, [panelSearch]);

  function openPanel(panel: Exclude<CopilotPanel, null>) {
    setPanelSearch("");
    setSelectedCapability(null);
    setActivePanel(panel);
  }

  function closePanel() {
    setSelectedCapability(null);
    setActivePanel(null);
  }

  function startNewConversation() {
    setThreadId(`thread-${Date.now()}`);
    setMessages([createWelcomeMessage()]);
    setCollapsedMessages({});
    setInput("");
    closePanel();
  }

  function openThread(thread: CopilotThread) {
    setThreadId(thread.id);
    try {
      const raw = localStorage.getItem(threadStorageKey(draftOwner, thread.id));
      const parsed = raw ? JSON.parse(raw) as CopilotMessage[] : null;
      setMessages(Array.isArray(parsed) && parsed.length ? parsed : [createWelcomeMessage()]);
    } catch {
      setMessages([createWelcomeMessage()]);
    }
    closePanel();
  }

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
      mode,
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
        mode,
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
    <section className={`copilot-page${railCollapsed ? " is-rail-collapsed" : ""}`}>
      <aside className="copilot-thread-rail">
        <div className="copilot-rail-brand">
          <img src="/brand/logo-icon.png" alt="" />
          <div><strong>ValuSee</strong><span>AI 导购</span></div>
        </div>
        <button type="button" className="copilot-new-thread" onClick={startNewConversation}>
          <Plus size={17} />
          开启新对话
        </button>
        <label className="copilot-thread-search">
          <Search size={15} />
          <input value={threadSearch} onChange={(event) => setThreadSearch(event.target.value)} placeholder="搜索对话" />
          <kbd>⌘ K</kbd>
        </label>
        <div className="copilot-thread-filter"><span>对话历史</span><small>{filteredThreads.length}</small></div>
        <div className="copilot-thread-list">
          {filteredThreads.map((thread) => (
            <button type="button" key={thread.id} className={thread.id === threadId ? "active" : ""} onClick={() => openThread(thread)}>
              <MessageSquare size={15} />
              <span><strong>{thread.title}</strong><small>{thread.preview}</small></span>
              <time>{new Date(thread.updatedAt).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" })}</time>
            </button>
          ))}
          {!filteredThreads.length && <div className="copilot-thread-empty"><History size={17} /><span>还没有历史对话</span></div>}
        </div>
        <div className="copilot-rail-footer">
          <div className="copilot-user-avatar"><UserRound size={17} /></div>
          <span><strong>{signedIn ? "已登录账户" : "本地体验账户"}</strong><small>{candidateCount ? `${candidateCount} 个候选商品` : "准备开始购物决策"}</small></span>
        </div>
      </aside>
      <header className="copilot-head">
        <div>
          <span className="section-kicker">AI 导购工作台</span>
          <h1>{currentThreadTitle}</h1>
          <p>ValuSee AI 导购会围绕预算、用途、SKU 和来源证据持续追问，帮你把购买决定说清楚。</p>
        </div>
        <div className="copilot-top-actions">
          <button type="button" title={railCollapsed ? "展开对话栏" : "收起对话栏"} aria-label={railCollapsed ? "展开对话栏" : "收起对话栏"} onClick={() => setRailCollapsed((value) => !value)}><PanelLeft size={16} /></button>
          <button type="button" className="copilot-top-user" title="用户账户"><UserRound size={16} /></button>
        </div>
      </header>

      <div className="copilot-layout copilot-layout-full">
        <section className="copilot-stream panel">
          <div className="copilot-stream-head">
            <div>
              <span>当前对话</span>
              <h2>和 ValuSee 一起做决定</h2>
            </div>
            <div className="copilot-context-actions">
              <button type="button" onClick={onOpenAnalyze} disabled={!candidateCount}><ArrowUpRight size={15} />对比工作台 {candidateCount || ""}</button>
              <button type="button" onClick={() => openPanel("mode")}><SlidersHorizontal size={15} />{activeMode.label}</button>
              <button type="button" onClick={() => openPanel("capabilities")}><Sparkles size={15} />AI 能力</button>
              <button type="button" onClick={() => openPanel("sources")}><Database size={15} />来源 {latestResponse?.sources.length || 0}</button>
            </div>
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
                      {message.role === "user" ? <span className="copilot-message-avatar user"><UserRound size={14} /></span> : <img className="copilot-message-avatar" src="/brand/xiaozhi.png" alt="ValuSee" />}
                      <span>{message.role === "user" ? "我" : "ValuSee"} · {modeLabel(message.mode)}</span>
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
                  <img className="copilot-message-avatar" src="/brand/xiaozhi.png" alt="ValuSee" />
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
                <button type="button" onClick={() => openPanel("mode")}><SlidersHorizontal size={13} />{activeMode.label}</button>
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
        <aside className="copilot-state-mirror" aria-hidden="true">
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

          <section className="copilot-card copilot-ai-board">
            <span>AI 能力地图</span>
            <h2>透明能力图谱</h2>
            <div className="copilot-capability-sections">
              <div className="copilot-capability-group">
                <div className="copilot-capability-group-title">
                  <Database size={14} />
                  <strong>RAG</strong>
                  <small>{RAG_KNOWLEDGE_BASES.length}</small>
                </div>
                <div className="copilot-capability-list">
                  {RAG_KNOWLEDGE_BASES.map((item) => (
                    <div
                      key={item.id}
                      className="copilot-capability-row"
                    >
                      <Database size={15} />
                      <div>
                        <strong>{item.name}</strong>
                        <small>{item.detail}</small>
                        <div className="copilot-capability-chips">
                          {item.contents.slice(0, 3).map((content) => <i key={content.label}>{content.label}</i>)}
                        </div>
                      </div>
                      <em>{item.status}</em>
                    </div>
                  ))}
                </div>
              </div>

              <div className="copilot-capability-group">
                <div className="copilot-capability-group-title">
                  <Wrench size={14} />
                  <strong>Skills</strong>
                  <small>{COPILOT_SKILLS.length}</small>
                </div>
                <div className="copilot-capability-list">
                  {COPILOT_SKILLS.map((item) => (
                    <div
                      key={item.id}
                      className="copilot-capability-row"
                    >
                      <Wrench size={15} />
                      <div>
                        <strong>{item.name}</strong>
                        <small>{item.detail}</small>
                        <div className="copilot-capability-chips">
                          {item.contents.slice(0, 3).map((content) => <i key={content.label}>{content.label}</i>)}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="copilot-capability-group">
                <div className="copilot-capability-group-title">
                  <PlugZap size={14} />
                  <strong>MCP</strong>
                  <small>{COPILOT_MCPS.length}</small>
                </div>
                <div className="copilot-capability-list">
                  {COPILOT_MCPS.map((item) => (
                    <div
                      key={item.id}
                      className="copilot-capability-row"
                    >
                      <PlugZap size={15} />
                      <div>
                        <strong>{item.name}</strong>
                        <small>{item.detail}</small>
                        <div className="copilot-capability-chips">
                          {item.contents.slice(0, 3).map((content) => <i key={content.label}>{content.label}</i>)}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
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

          <section className="copilot-card copilot-sidebar-actions">
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
      {activePanel && (
        <div className="copilot-modal-backdrop" role="presentation" onMouseDown={closePanel}>
          <section className="copilot-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
            <header className="copilot-modal-head">
              <div className="copilot-modal-title">
                {activePanel === "capabilities" && selectedCapabilityItem && (
                  <button type="button" className="copilot-modal-back" title="返回能力列表" aria-label="返回能力列表" onClick={() => { setSelectedCapability(null); setPanelSearch(""); }}><ArrowLeft size={17} /></button>
                )}
                <div><span>ValuSee AI 工作台</span><h2>{selectedCapabilityItem?.name || (activePanel === "search" ? "搜索对话与能力" : activePanel === "mode" ? "选择导购模式" : activePanel === "capabilities" ? "AI 能力地图" : activePanel === "sources" ? "本轮来源" : activePanel === "followups" ? "继续追问" : "候选证据")}</h2></div>
              </div>
              <button type="button" title="关闭" onClick={closePanel}><X size={18} /></button>
            </header>
            {!(activePanel === "capabilities" && selectedCapabilityItem) && (
              <label className="copilot-modal-search"><SearchCode size={17} /><input autoFocus value={panelSearch} onChange={(event) => setPanelSearch(event.target.value)} placeholder={activePanel === "mode" ? "搜索模式" : "搜索名称、能力或关键词"} /><kbd>⌘ K</kbd></label>
            )}
            {activePanel === "search" && (
              <div className="copilot-search-results">
                <button type="button" onClick={() => { setActivePanel(null); setInput(panelSearch); }}><MessageSquare size={16} /><span><strong>在当前对话中提问</strong><small>{panelSearch || "输入问题后回车发送"}</small></span><ChevronRight size={15} /></button>
                {filteredThreads.slice(0, 8).map((thread) => <button type="button" key={thread.id} onClick={() => openThread(thread)}><History size={16} /><span><strong>{thread.title}</strong><small>{thread.preview}</small></span><ChevronRight size={15} /></button>)}
                {panelItems.slice(0, 6).map(({ kind, item }) => <button type="button" key={`${kind}-${item.id}`} onClick={() => { setActivePanel("capabilities"); setPanelSearch(item.name); }}><Sparkles size={16} /><span><strong>{item.name}</strong><small>{capabilityKindLabel(kind)} · {item.detail}</small></span><ChevronRight size={15} /></button>)}
              </div>
            )}
            {activePanel === "mode" && (
              <div className="copilot-modal-grid copilot-mode-modal">
                {COPILOT_MODES.filter((item) => !panelSearch.trim() || `${item.label} ${item.title} ${item.hint}`.toLowerCase().includes(panelSearch.toLowerCase())).map((item) => { const Icon = item.icon; return <button type="button" key={item.key} className={mode === item.key ? "active" : ""} onClick={() => { setMode(item.key); setActivePanel(null); }}><Icon size={18} /><span><strong>{item.label}</strong><small>{item.title} · {item.hint}</small></span>{mode === item.key && <ShieldCheck size={15} />}</button>; })}
              </div>
            )}
            {activePanel === "capabilities" && selectedCapability && selectedCapabilityItem ? (
              <div className="copilot-modal-capability-detail">
                <CapabilityDetail item={selectedCapabilityItem} kind={selectedCapability.kind} />
              </div>
            ) : activePanel === "capabilities" && (
              <div className="copilot-modal-capabilities">
                {panelItems.map(({ kind, item }) => <button type="button" key={`${kind}-${item.id}`} className="copilot-modal-capability" onClick={() => { setSelectedCapability({ kind, id: item.id }); setPanelSearch(""); }}><span className="copilot-capability-icon">{kind === "rag" ? <Database size={16} /> : kind === "skill" ? <Wrench size={16} /> : <PlugZap size={16} />}</span><span><strong>{item.name}</strong><small>{capabilityKindLabel(kind)} · {item.detail}</small><em>{item.contents.slice(0, 3).map((content) => content.label).join(" · ")}</em></span><ChevronRight size={15} /></button>)}
                {!panelItems.length && <div className="copilot-modal-empty">没有匹配的能力或关键词。</div>}
              </div>
            )}
            {activePanel === "sources" && <div className="copilot-modal-list">{(latestResponse?.sources || []).map((source) => <article key={`${source.provider}-${source.status}`}><strong>{sourceLabel(source.provider)}</strong><span>{source.status === "ok" ? `${source.count || 0} 条结果` : sourceHealthText(source.status)}</span><small>{source.status === "ok" ? "已返回可追溯商品结果" : source.error || "请更换关键词或补充信息"}</small></article>)}{!latestResponse?.sources.length && <div className="copilot-modal-empty">发送一次商品需求后，这里会展示来源状态。</div>}</div>}
            {activePanel === "followups" && <div className="copilot-modal-list">{followUps.filter((item) => !panelSearch.trim() || `${item.label} ${item.hint}`.toLowerCase().includes(panelSearch.toLowerCase())).map((item) => <button type="button" key={item.label} onClick={() => { setActivePanel(null); runMessageSearch(item.query); }}><span><strong>{item.label}</strong><small>{item.hint}</small></span><ChevronRight size={15} /></button>)}</div>}
            {activePanel === "evidence" && <div className="copilot-modal-products">{latestResults.map((result) => { const product = result.product; return <article key={`${result.provider}-${product.url}-${product.sku}`}><div className="copilot-mini-thumb">{product.image_url ? <img src={product.image_url} alt="" /> : <Laptop size={18} />}</div><span><strong>{product.title}</strong><small>{sourceLabel(result.provider)} · {money(finalPrice(product))}</small></span><button type="button" onClick={() => onAddCandidate(product)}><Plus size={14} /></button></article>; })}{!latestResults.length && <div className="copilot-modal-empty">当前对话还没有候选商品。</div>}</div>}
          </section>
        </div>
      )}
    </section>
  );
}
