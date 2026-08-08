import {
  Bell,
  CheckCircle2,
  ClipboardList,
  CreditCard,
  History,
  LineChart,
  Loader2,
  Plus,
  ShieldCheck,
  Sparkles,
  Tag,
  Trash2,
} from 'lucide-react';
import { FormEvent, useMemo, useState } from 'react';

type ProductInput = {
  title: string;
  platform: string;
  url: string;
  brand: string;
  model: string;
  sku: string;
  specs: Record<string, string>;
  price: number;
  coupon: number;
  platform_discount: number;
  member_discount: number;
  subsidy: number;
  pay_discount: number;
  shipping: number;
  gift_value: number;
  condition: string;
  official_store: boolean;
  return_days: number;
  warranty_months: number;
  notes: string;
};

type DecisionResult = {
  task_id: string;
  status: string;
  result: {
    best_index: number | null;
    recommendation: string;
    recommendation_reason: string;
    summary: string;
    comparison_rows: Array<{
      index: number;
      title: string;
      platform: string;
      model: string;
      same_item_relation: string;
      same_item_confidence: number;
      final_price: number;
      value_score: number;
      risk_level: string;
      suitable_for_user: boolean;
    }>;
    price_breakdowns: Array<Record<string, number>>;
    risk_reports: Array<{
      overall_risk: string;
      price_risk: string;
      spec_risk: string;
      store_risk: string;
      after_sales_risk: string;
      reasons: string[];
    }>;
    report_markdown: string;
  };
};

const sampleProducts: ProductInput[] = [
  {
    title: 'AirPods Pro 2 USB-C 官方旗舰店',
    platform: '京东',
    url: 'https://example.com/jd-airpods-usbc',
    brand: 'Apple',
    model: 'AirPods Pro 2',
    sku: 'APP2-USBC',
    specs: { version: 'USB-C', generation: '2' },
    price: 1799,
    coupon: 140,
    platform_discount: 60,
    member_discount: 0,
    subsidy: 0,
    pay_discount: 20,
    shipping: 0,
    gift_value: 0,
    condition: 'new',
    official_store: true,
    return_days: 7,
    warranty_months: 12,
    notes: '官方店铺，适合 iPhone 用户，主动降噪。',
  },
  {
    title: 'AirPods Pro 2 Lightning 低价现货',
    platform: '拼多多',
    url: 'https://example.com/pdd-airpods-lightning',
    brand: 'Apple',
    model: 'AirPods Pro 2',
    sku: 'APP2-LIGHT',
    specs: { version: 'Lightning', generation: '2' },
    price: 1488,
    coupon: 80,
    platform_discount: 30,
    member_discount: 0,
    subsidy: 0,
    pay_discount: 0,
    shipping: 0,
    gift_value: 0,
    condition: 'new',
    official_store: false,
    return_days: 7,
    warranty_months: 12,
    notes: '价格更低，但接口不同，店铺资质需确认。',
  },
];

const featureCards = [
  { icon: Tag, title: '帮我比', text: '多链接同款判断，算清真实到手价。' },
  { icon: CheckCircle2, title: '值不值', text: '结合预算、设备和风险给购买建议。' },
  { icon: Bell, title: '等等再买', text: '设置目标价，到价后第一时间提醒。' },
  { icon: History, title: '我的购买', text: '跟踪保价、退货、保修和耗材周期。' },
  { icon: ClipboardList, title: '买前清单', text: '把纠结的商品放进同一个决策报告。' },
];

const relationText: Record<string, string> = {
  same: '同款',
  similar: '相似',
  different: '非同款',
  uncertain: '待确认',
};

const riskText: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
};

export function App() {
  const [goal, setGoal] = useState('想买一副适合 iPhone 的降噪耳机，预算 1800 元以内。');
  const [budget, setBudget] = useState(1800);
  const [products, setProducts] = useState<ProductInput[]>(sampleProducts);
  const [result, setResult] = useState<DecisionResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const bestRow = useMemo(() => {
    if (!result?.result.comparison_rows.length || result.result.best_index === null) return null;
    return result.result.comparison_rows[result.result.best_index];
  }, [result]);

  async function runDecision(event?: FormEvent) {
    event?.preventDefault();
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/v1/shopping/decide', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          goal,
          products,
          profile: {
            budget,
            use_case: goal,
            devices: ['iPhone', 'MacBook Pro'],
            brand_preferences: ['Apple'],
            sensitivities: ['售后', '接口兼容', '保修'],
            acceptable_risk: 'medium',
          },
          require_human_review: false,
        }),
      });
      if (!response.ok) {
        const body = await response.text();
        throw new Error(body || '分析失败');
      }
      setResult(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : '分析失败');
    } finally {
      setLoading(false);
    }
  }

  function updateProduct(index: number, patch: Partial<ProductInput>) {
    setProducts((items) => items.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)));
  }

  function addProduct() {
    setProducts((items) => [
      ...items,
      {
        title: '新商品候选',
        platform: '淘宝',
        url: '',
        brand: '',
        model: '',
        sku: '',
        specs: {},
        price: 0,
        coupon: 0,
        platform_discount: 0,
        member_discount: 0,
        subsidy: 0,
        pay_discount: 0,
        shipping: 0,
        gift_value: 0,
        condition: 'new',
        official_store: false,
        return_days: 7,
        warranty_months: 12,
        notes: '',
      },
    ]);
  }

  function removeProduct(index: number) {
    setProducts((items) => items.filter((_, itemIndex) => itemIndex !== index));
  }

  return (
    <main className="valuesee-app">
      <section className="hero-panel">
        <nav className="topbar">
          <div className="brand-lockup">
            <div className="brand-mark">见</div>
            <div>
              <strong>见值 ValuSee</strong>
              <span>买之前，先见值</span>
            </div>
          </div>
          <div className="top-actions">
            <button type="button">价格趋势</button>
            <button type="button">降价提醒</button>
            <button type="button">我的购买</button>
          </div>
        </nav>

        <div className="hero-grid">
          <div className="hero-copy">
            <div className="eyebrow">
              <Sparkles size={18} />
              AI 购物决策与省钱 Agent
            </div>
            <h1>把纠结的商品链接发给我，先看它到底值不值得买。</h1>
            <p>
              ValuSee 会识别同款与规格差异，核算真实到手价，结合预算和使用场景给出购买建议，并持续管理降价、保价和退货期限。
            </p>
            <form className="decision-box" onSubmit={runDecision}>
              <textarea value={goal} onChange={(event) => setGoal(event.target.value)} />
              <div className="decision-controls">
                <label>
                  预算
                  <input type="number" min={0} value={budget} onChange={(event) => setBudget(Number(event.target.value))} />
                </label>
                <button type="submit" disabled={loading}>
                  {loading ? <Loader2 className="spin" size={18} /> : <LineChart size={18} />}
                  立即分析
                </button>
              </div>
            </form>
            {error ? <div className="error-banner">{error}</div> : null}
          </div>

          <div className="mascot-stage" aria-label="ValuSee brand mascot">
            <div className="mascot-card">
              <div className="spark spark-a" />
              <div className="mascot-face">
                <span />
                <span />
                <i />
              </div>
              <div className="mascot-badge">
                <CheckCircle2 size={36} />
              </div>
              <div className="price-chip">值得买</div>
            </div>
            <div className="curve-line" />
          </div>
        </div>
      </section>

      <section className="feature-strip">
        {featureCards.map((item) => (
          <article key={item.title}>
            <item.icon size={24} />
            <strong>{item.title}</strong>
            <span>{item.text}</span>
          </article>
        ))}
      </section>

      <section className="workspace-grid">
        <div className="product-panel">
          <div className="section-heading">
            <div>
              <span>候选商品</span>
              <h2>先把要纠结的商品放进来</h2>
            </div>
            <button type="button" className="soft-button" onClick={addProduct}>
              <Plus size={17} />
              添加
            </button>
          </div>

          <div className="product-list">
            {products.map((product, index) => (
              <article className="product-editor" key={`${product.title}-${index}`}>
                <div className="product-editor-head">
                  <span>候选 {index + 1}</span>
                  <button type="button" onClick={() => removeProduct(index)} disabled={products.length <= 1}>
                    <Trash2 size={16} />
                  </button>
                </div>
                <input value={product.title} onChange={(event) => updateProduct(index, { title: event.target.value })} />
                <div className="field-grid">
                  <label>
                    平台
                    <input value={product.platform} onChange={(event) => updateProduct(index, { platform: event.target.value })} />
                  </label>
                  <label>
                    品牌
                    <input value={product.brand} onChange={(event) => updateProduct(index, { brand: event.target.value })} />
                  </label>
                  <label>
                    型号
                    <input value={product.model} onChange={(event) => updateProduct(index, { model: event.target.value })} />
                  </label>
                  <label>
                    标价
                    <input type="number" value={product.price} onChange={(event) => updateProduct(index, { price: Number(event.target.value) })} />
                  </label>
                  <label>
                    优惠券
                    <input type="number" value={product.coupon} onChange={(event) => updateProduct(index, { coupon: Number(event.target.value) })} />
                  </label>
                  <label>
                    平台补贴
                    <input type="number" value={product.platform_discount} onChange={(event) => updateProduct(index, { platform_discount: Number(event.target.value) })} />
                  </label>
                </div>
                <label className="check-row">
                  <input type="checkbox" checked={product.official_store} onChange={(event) => updateProduct(index, { official_store: event.target.checked })} />
                  官方/自营店铺
                </label>
              </article>
            ))}
          </div>
        </div>

        <div className="result-panel">
          <div className="section-heading">
            <div>
              <span>决策结果</span>
              <h2>看价格、看风险、看是否适合你</h2>
            </div>
            <CreditCard size={28} />
          </div>

          {result ? (
            <div className="result-stack">
              <div className="recommend-card">
                <span>{bestRow ? `推荐候选 ${bestRow.index + 1}` : '等待更多信息'}</span>
                <h3>{result.result.summary}</h3>
                <p>{result.result.recommendation_reason}</p>
              </div>

              <div className="comparison-table">
                <div className="table-row table-head">
                  <span>商品</span>
                  <span>到手价</span>
                  <span>同款</span>
                  <span>风险</span>
                  <span>建议</span>
                </div>
                {result.result.comparison_rows.map((row) => (
                  <div className="table-row" key={row.index}>
                    <strong>{row.title}</strong>
                    <span>¥{row.final_price.toFixed(0)}</span>
                    <span>{relationText[row.same_item_relation] ?? row.same_item_relation}</span>
                    <span className={`risk risk-${row.risk_level}`}>{riskText[row.risk_level] ?? row.risk_level}</span>
                    <span>{row.suitable_for_user ? '适合' : '谨慎'}</span>
                  </div>
                ))}
              </div>

              <div className="risk-grid">
                {result.result.risk_reports.map((risk, index) => (
                  <article key={index}>
                    <ShieldCheck size={20} />
                    <strong>候选 {index + 1} 风险：{riskText[risk.overall_risk] ?? risk.overall_risk}</strong>
                    <p>{risk.reasons.slice(0, 2).join('；') || '未发现明显风险。'}</p>
                  </article>
                ))}
              </div>
            </div>
          ) : (
            <div className="empty-result">
              <Tag size={42} />
              <h3>点击“立即分析”生成第一份购买决策报告</h3>
              <p>报告会展示同款判断、真实到手价、风险等级和推荐理由。</p>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
