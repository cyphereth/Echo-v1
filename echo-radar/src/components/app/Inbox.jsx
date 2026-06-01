import { Icon } from '../shared/icons';
import { PlatformMark, SeverityRing, Sparkline, Eyebrow } from '../shared/primitives';
import { sevTone, PHASE } from '../../data/mentions';
import styles from './app.module.css';

function StatusFlag({ status }) {
  if (status === 'sent')  return <span className={styles.flag} style={{ color: 'var(--sev-calm)' }}><Icon name="check" size={13} />Отправлено</span>;
  if (status === 'human') return <span className={styles.flag} style={{ color: 'var(--fg-3)' }}><Icon name="eye" size={13} />Решает человек</span>;
  return <span className={styles.flag} style={{ color: 'var(--brand-bright)' }}><span className={styles.dotLive} />Новое</span>;
}

export function MentionRow({ m, selected, onClick }) {
  const t = sevTone(m.severity);
  const phase = PHASE[m.phase];
  const accent = m.lane === 'none' ? 'var(--line-strong)' : t.color;
  return (
    <button className={styles.row} data-selected={selected ? '1' : '0'}
      style={{ borderLeftColor: accent }} onClick={onClick}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
        <PlatformMark platform={m.platform} size={30} />
        <div style={{ flex: 1, minWidth: 0, lineHeight: 1.25 }}>
          <div style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--fg-1)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>@{m.author}</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-3)' }}>{(m.followers/1000).toFixed(m.followers >= 10000 ? 0 : 1)}k · {m.ago}</div>
        </div>
        {m.lane === 'none'
          ? <span className={styles.humanBadge}><Icon name="eye" size={16} color="var(--fg-3)" /></span>
          : <SeverityRing value={m.severity} size={46} stroke={5} tone={t} />}
      </div>

      <div className={styles.rowText}>{m.text}</div>

      <div className={styles.rowFoot}>
        <Sparkline data={m.views} color={phase.color} w={72} h={26} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontFamily: 'var(--font-mono)', fontSize: 11, color: phase.color, fontWeight: 600 }}>
            <Icon name={phase.icon} size={13} />{phase.label} · {m.rate}
          </span>
          <StatusFlag status={m.status} />
        </div>
        {m.humor && <span className={styles.humor}><Icon name="sparkles" size={12} />Юмор</span>}
      </div>
    </button>
  );
}

export function LaneColumn({ icon, title, accent, sub, items, selectedId, onSelect }) {
  return (
    <section className={styles.laneCol}>
      <header className={styles.laneHead}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 9 }}>
          <Icon name={icon} size={16} color={accent} />
          <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-1)' }}>{title}</span>
          <span className={styles.count} style={{ color: accent }}>{items.length}</span>
        </span>
        <Eyebrow>{sub}</Eyebrow>
      </header>
      <div className={styles.laneList}>
        {items.map(m => <MentionRow key={m.id} m={m} selected={selectedId === m.id} onClick={() => onSelect(m.id)} />)}
        {items.length === 0 && <div className={styles.empty}>Тихо. Новых сигналов нет.</div>}
      </div>
    </section>
  );
}

export function Inbox({ data, selectedId, onSelect }) {
  const pr  = data.filter(m => m.lane === 'PR' || m.lane === 'none');
  const smm = data.filter(m => m.lane === 'SMM');
  return (
    <div className={styles.inbox}>
      <LaneColumn icon="flame" title="PR · срочное" accent="#FF7A87" sub="высокая виральность"
        items={pr} selectedId={selectedId} onSelect={onSelect} />
      <LaneColumn icon="sparkles" title="SMM" accent="var(--brand-bright)" sub="ответы и возможности"
        items={smm} selectedId={selectedId} onSelect={onSelect} />
    </div>
  );
}
