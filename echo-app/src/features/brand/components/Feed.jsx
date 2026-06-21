import { useState } from 'react';
import { Icon } from '../../../core/components/icons';
import styles from '../../../components/app/feed.module.css';

// Lane display helpers (inlined — removes dependency on data/mock)
function getLaneColor(lane) {
  if (lane === 'competitor') return 'var(--warn)';
  if (lane === 'niche')      return 'var(--info, #6c8ebf)';
  return 'var(--brand)';
}

const TABS = [
  { key: 'brand',      label: 'Мой бренд',  icon: 'building' },
  { key: 'competitor', label: 'Конкуренты', icon: 'users' },
  { key: 'niche',      label: 'Ниша',       icon: 'radio' },
];

function fmtNum(n) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000)    return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function SevBadge({ sev }) {
  if (sev >= 80) return <span className={styles.sevBadge} style={{ background: 'var(--neg-dim)', color: 'var(--neg)' }}>🔥 {sev}</span>;
  if (sev >= 40) return <span className={styles.sevBadge} style={{ background: 'var(--rising-dim)', color: 'var(--rising)' }}>⚡ {sev}</span>;
  if (sev > 0)   return <span className={styles.sevBadge} style={{ background: 'var(--surface-3)', color: 'var(--fg-3)' }}>{sev}</span>;
  return null;
}

function FeedCard({ item, active, onClick }) {
  const laneColor    = getLaneColor(item.lane);
  const pendingCount = item.comments.filter(c => c.suggestedReply && c.status === 'pending').length;

  return (
    <button className={styles.card} data-active={active ? '1' : '0'} onClick={onClick}>
      <div className={styles.cardTop}>
        <span className={styles.laneDot} style={{ background: laneColor }} />
        <Icon name={item.platform} size={13} color="var(--fg-3)" />
        <span className={styles.author}>@{item.author}</span>
        {item.authorFollowers > 0 && (
          <span className={styles.followers}>{fmtNum(item.authorFollowers)}</span>
        )}
        <span className={styles.ago}>{item.ago}</span>
      </div>

      <p className={styles.title}>{item.title}</p>

      <div className={styles.cardStats}>
        {item.views > 0 && (
          <span className={styles.stat}>
            <Icon name="eye" size={12} color="var(--fg-4)" />
            {fmtNum(item.views)}
          </span>
        )}
        {item.likes > 0 && (
          <span className={styles.stat}>
            <Icon name="heart" size={12} color="var(--fg-4)" />
            {fmtNum(item.likes)}
          </span>
        )}
        <span className={styles.stat}>
          <Icon name="messageCircle" size={12} color="var(--fg-4)" />
          {fmtNum(item.commentsCount)}
        </span>
        {item.lane === 'brand' && item.negativeCommentPct > 0 && (
          <span className={styles.stat} style={{ color: 'var(--neg)' }}>
            <Icon name="activity" size={12} color="var(--neg)" />
            {item.negativeCommentPct}% негатив
          </span>
        )}
        {item.lane === 'brand' && <SevBadge sev={item.severity} />}
        {item.url && (
          <a href={item.url} target="_blank" rel="noopener noreferrer"
            className={styles.linkBtn}
            onClick={e => e.stopPropagation()}>
            <Icon name="externalLink" size={11} />
          </a>
        )}
      </div>
    </button>
  );
}

// Brand Feed is always tabbed (lanes mode)
export function BrandFeed({ items: allItems = [], selectedId, onSelect }) {
  const [tab, setTab] = useState('brand');
  const items = allItems.filter(i => i.lane === tab);

  const counts = {
    brand:      allItems.filter(i => i.lane === 'brand').length,
    competitor: allItems.filter(i => i.lane === 'competitor').length,
    niche:      allItems.filter(i => i.lane === 'niche').length,
  };

  return (
    <div className={styles.feed}>
      <div className={styles.tabs}>
        {TABS.map(t => (
          <button key={t.key} className={styles.tab} data-active={tab === t.key ? '1' : '0'}
            onClick={() => setTab(t.key)}>
            {t.label}
            <span className={styles.tabCount} style={{
              background: tab === t.key ? getLaneColor(t.key) + '22' : 'var(--surface-2)',
              color: tab === t.key ? getLaneColor(t.key) : 'var(--fg-4)',
            }}>
              {counts[t.key]}
            </span>
          </button>
        ))}
      </div>
      <div className={styles.list}>
        {items.length === 0 && <div style={{ padding: 24, color: 'var(--fg-3)', fontSize: 13 }}>Пока пусто — источники собираются.</div>}
        {items.map(item => (
          <FeedCard key={item.id} item={item}
            active={selectedId === item.id}
            onClick={() => onSelect(item.id)} />
        ))}
      </div>
    </div>
  );
}
