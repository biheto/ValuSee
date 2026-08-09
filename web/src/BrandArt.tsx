import { Check, Sparkles } from 'lucide-react';
import { useState } from 'react';

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
  const [mood, setMood] = useState(0);
  const responses = ['我来帮你看清同款', '到手价已经算好了', '买完我还会盯住保价'];

  function interact() {
    setMood((current) => (current + 1) % responses.length);
  }

  return (
    <div className={`value-mascot mood-${mood}`} role="button" tabIndex={0} aria-label="与小值互动" onClick={interact} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') interact(); }}>
      <span className="mascot-response" aria-live="polite">{responses[mood]}</span>
      <span className="mascot-chip mascot-chip-match">同款识别</span>
      <span className="mascot-chip mascot-chip-price">到手价</span>
      <span className="mascot-chip mascot-chip-alert">保价提醒</span>
      <span className="mascot-spark mascot-spark-one" />
      <span className="mascot-spark mascot-spark-two" />
      <span className="mascot-burst mascot-burst-one" />
      <span className="mascot-burst mascot-burst-two" />
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
