// Brand dispatch inbox — двухполосная сетка PR (срочное) | SMM.
// Hero-компонент MentionRow: SeverityRing + Sparkline + phase label + StatusFlag.
// Канон: project/ui_kits/app/inbox.jsx. Источник lanes — бэкенд /inbox?brand_id=
// (pr / smm), внутри бренда ещё source-полосы (brand/competitor/niche) →
// распределяем: PR = source brand|competitor AND tone negative/high-sev;
// остальное → SMM.
import { Icon } from '../../../core/components/icons';
import { SeverityRing } from '../../../core/components/SeverityRing';
import { Sparkline } from '../../../core/components/Sparkline';
import { sevTone, fmtNum, PHASE } from '../../../core/utils/format';
import styles from '../../../components/app/feed.module.css';

// куда положить карточку: PR (срочное) если негативная/конкурент/high-sev, иначе SMM
function laneOf(item) {
  if (item.severity >= 75) return 'pr';
  if (item.lane === 'competitor' && item.tone === 'negative') return 'pr';
  if (item.lane === 'brand' && item.tone === 'negative' && item.severity >= 45) return 'pr';
  if (item.status === 'human') return 'none';
  return 'smm';
}

function StatusFlag({ item }) {
  if (item.status === 'sent' || item.status === 'approved')
    return <span className={styles.flag} style={{ color: 'var(--sev-calm)' }}><Icon name="check" size={12} color="var(--sev-calm)" />Отправлено</span>;
  if (item.status === 'human' || item.status === 'none')
    return <span className={styles.flag} style={{ color: 'var(--fg-3)' }}><Icon name="eye" size={12} color="var(--fg-3)" />Решает человек</span>;
  return <span className={styles.flag} style={{ color: 'var(--brand-bright)' }}><span className={styles.dotLive} />Новое</span>;
}

function MentionRow({ item, active, onClick }) {
  const tone = sevTone(item.severity);
  const phase = PHASE[item.phase] || PHASE.unknown;
  const views = item.viewsSeries || (item.views ? [item.views] : []);

  return (
    <button className={styles.row} data-selected={active ? '1' : '0'}
      onClick={onClick}
      style={{ borderLeftColor: item.status === 'human' ? 'var(--line-strong)' : tone.color }}>
      <div className={styles.rowTop}>
        <PlatformMini platform={item.platform} />
        <div className={styles.rowAuthor}>
          <div className={styles.rowAuthorName}>@{item.author}</div>
          <div className={styles.rowAuthorMeta}>
            {item.authorFollowers > 0 ? `${fmtNum(item.authorFollowers)} подп.` : ''}
            {item.authorFollowers > 0 && item.ago ? ' · ' : ''}
            {item.ago}
          </div>
        </div>
        {item.status === 'human' ? (
          <span className={styles.humanRing}><Icon name="eye" size={16} color="var(--fg-3)" /></span>
        ) : (
          <SeverityRing value={item.severity} size={46} stroke={5} />
        )}
      </div>
      <div className={styles.rowText}>{item.title}</div>
      <div className={styles.rowFoot}>
        {views.length > 1 && <Sparkline data={views} color={phase.color} w={72} h={26} />}
        <span className={styles.phaseLabel} style={{ color: phase.color }}>
          {phase.label}
        </span>
        <StatusFlag item={item} />
        {item.humor && <span className={styles.humor}>Юмор</span>}
      </div>
    </button>
  );
}

function PlatformMini({ platform }) {
  const map = {
    instagram: { color: '#E1306C', bg: 'rgba(225,48,108,.14)' },
    tiktok:    { color: '#EAF1F8', bg: '#0A1420' },
    telegram:  { color: '#29A9EB', bg: 'rgba(41,169,235,.14)' },
  };
  const p = map[platform] || map.instagram;
  return (
    <span style={{
      width: 30, height: 30, borderRadius: 7, background: p.bg, flex: 'none',
      display: 'grid', placeItems: 'center', border: '1px solid var(--line-2)',
    }}>
      <Icon name={platform} size={16} color={p.color} />
    </span>
  );
}

function LaneColumn({ title, accent, icon, sub, items, selectedId, onSelect }) {
  return (
    <div className={styles.lane}>
      <div className={styles.laneHead}>
        <span className={styles.laneHeadTitle}>
          <Icon name={icon} size={15} color={accent} />
          {title}
        </span>
        <span className={styles.count} style={{ color: accent }}>{items.length}</span>
        <span className={styles.laneHeadSub}>{sub}</span>
      </div>
      <div className={styles.laneList}>
        {items.length === 0
          ? <div className={styles.empty}>Тихо. Новых сигналов нет.</div>
          : items.map(item => (
              <MentionRow key={item.id} item={item} active={selectedId === item.id}
                onClick={() => onSelect(item.id)} />
            ))}
      </div>
    </div>
  );
}

export function BrandFeed({ items = [], selectedId, onSelect }) {
  const pr = items.filter(i => laneOf(i) === 'pr');
  const smm = items.filter(i => laneOf(i) === 'smm');

  return (
    <div className={styles.inbox}>
      <LaneColumn
        title="PR · срочное"
        accent="#FF7A87"
        icon="flame"
        sub="тушим пожар"
        items={pr}
        selectedId={selectedId}
        onSelect={onSelect}
      />
      <LaneColumn
        title="SMM"
        accent="var(--brand-bright)"
        icon="sparkles"
        sub="амбассадоры · вопросы"
        items={smm}
        selectedId={selectedId}
        onSelect={onSelect}
      />
    </div>
  );
}
