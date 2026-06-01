import { useState } from 'react';
import { Icon } from '../shared/icons';
import { Button, Eyebrow } from '../shared/primitives';
import { ACTIVE_PROBES, AI_SUGGEST, KIND } from '../../data/probes';
import styles from './app.module.css';

export function ProbesScreen({ brandName }) {
  const [chips, setChips] = useState(AI_SUGGEST.map(q => ({ q, added: false })));
  const add = (i) => setChips(cs => cs.map((c, j) => j === i ? { ...c, added: true } : c));

  return (
    <div className={styles.probes}>
      <div>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800, letterSpacing: '-0.02em', color: 'var(--fg-1)' }}>Зонды</h2>
        <p style={{ margin: '8px 0 0', fontSize: 14, lineHeight: 1.6, color: 'var(--fg-2)', maxWidth: 640 }}>
          Зонд — это поисковый запрос по ключевому слову или хэштегу, которым Echo Radar
          непрерывно ищет упоминания <b style={{ color: 'var(--fg-1)' }}>{brandName ?? '…'}</b> в Instagram и TikTok.
          Чем точнее зонды — тем меньше шума и точнее severity.
        </p>
      </div>

      <div className={styles.onb}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <span className={styles.onbIc}><Icon name="sparkles" size={16} color="var(--brand-bright)" /></span>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--fg-1)' }}>AI-настройка зондов</div>
            <div style={{ fontSize: 12.5, color: 'var(--fg-3)' }}>Дайте ссылку на бренд — предложим ключевые слова и хэштеги</div>
          </div>
        </div>
        <div className={styles.onbInput}>
          <Icon name="link" size={15} color="var(--fg-3)" />
          <span style={{ flex: 1, color: 'var(--fg-1)', fontSize: 13.5 }}>papapizza.ru</span>
          <Button variant="primary" size="sm" icon="sparkles">Разобрать</Button>
        </div>
        <Eyebrow style={{ display: 'block', margin: '16px 0 10px' }}>Предложено AI — подтвердите нужные</Eyebrow>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {chips.map((c, i) => (
            <button key={i} className={styles.chipAI} data-added={c.added ? '1' : '0'} onClick={() => add(i)}>
              <Icon name={c.added ? 'check' : 'plus'} size={13} />{c.q}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.probeList}>
        <div className={styles.probeListHead}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 9 }}>
            <Icon name="radio" size={16} color="var(--brand-bright)" />
            <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-1)' }}>Активные зонды</span>
            <span className={styles.count} style={{ color: 'var(--brand-bright)' }}>{ACTIVE_PROBES.length}</span>
          </span>
          <Button variant="ghost" size="sm" icon="plus">Зонд вручную</Button>
        </div>
        {ACTIVE_PROBES.map((p, i) => (
          <div key={i} className={styles.probeRow}>
            <span className={styles.probeKind}>{KIND[p.kind]}</span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13.5, color: 'var(--fg-1)', fontWeight: 500 }}>{p.q}</span>
            </span>
            <span style={{ display: 'flex', gap: 5 }}>
              {p.pf.map(pf => <Icon key={pf} name={pf} size={15} color={pf === 'instagram' ? '#E1306C' : 'var(--fg-2)'} />)}
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, width: 86 }}>
              <Icon name={p.trend === 'up' ? 'trendingUp' : p.trend === 'down' ? 'trendingDown' : 'activity'} size={13}
                color={p.trend === 'up' ? 'var(--sev-rising)' : 'var(--fg-3)'} />
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--fg-2)' }}>{p.interval}</span>
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--fg-3)', width: 88, textAlign: 'right' }}>{p.mentions} упом.</span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--fg-2)', width: 84 }}>
              <span style={{ width: 7, height: 7, borderRadius: 999, background: p.hot ? 'var(--sev-rising)' : 'var(--sev-calm)', display: 'inline-block' }} />
              {p.last}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
