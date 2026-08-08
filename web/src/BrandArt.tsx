import { Check, Sparkles } from 'lucide-react';

export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <span className={`brand-mark${compact ? ' brand-mark-compact' : ''}`} aria-hidden="true">
      <Sparkles className="brand-mark-spark" strokeWidth={3} />
      <span className="brand-mark-glyph">见</span>
      <span className="brand-mark-corner"><Check strokeWidth={4} /></span>
    </span>
  );
}

export function BrandWordmark() {
  return (
    <div className="brand-wordmark" aria-label="ValuSee 见值">
      <BrandMark compact />
      <div><strong>ValuSee</strong><span>见值</span></div>
    </div>
  );
}

export function ValueMascot() {
  return (
    <div className="value-mascot" role="img" aria-label="ValuSee 小值品牌角色">
      <span className="mascot-spark mascot-spark-one" />
      <span className="mascot-spark mascot-spark-two" />
      <span className="mascot-arm mascot-arm-left" />
      <span className="mascot-arm mascot-arm-right" />
      <div className="mascot-body">
        <span className="mascot-tag-hole" />
        <div className="mascot-face">
          <span className="mascot-eye" />
          <span className="mascot-smile" />
          <span className="mascot-eye mascot-eye-right" />
        </div>
        <div className="mascot-value-card"><span>见</span></div>
        <span className="mascot-check"><Check strokeWidth={4} /></span>
      </div>
      <span className="mascot-foot mascot-foot-left" />
      <span className="mascot-foot mascot-foot-right" />
    </div>
  );
}
