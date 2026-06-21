import { useState } from 'react';
import { Icon } from '../../core/components/icons';
import { getLaneColor } from '../../data/mock';
import styles from './feed.module.css';

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

function PlatformIcon({ platform }) {
  return (
    <span className={styles.platformBadge}>
      <Icon name={platform} size={13} />
      {platform === 'instagram' ? 'Instagram' : platform === 'tiktok' ? 'TikTok' : 'Telegram'}
    </span>
  );
}

function SevBadge({ sev }) {
  if (sev >= 80) return <span className={styles.sevBadge} style={{ background: 'var(--neg-dim)', color: 'var(--neg)' }}>🔥 {sev}</span>;
  if (sev >= 50) return <span className={styles.sevBadge} style={{ background: 'var(--rising-dim)', color: 'var(--rising)' }}>⚡ {sev}</span>;
  if (sev > 0)   return <span className={styles.sevBadge} style={{ background: 'var(--surface-3)', color: 'var(--fg-3)' }}>{sev}</span>;
  return null;
}

function FeedCard({ item, active, onClick }) {
  const laneColor   = getLaneColor(item.lane);
  const pendingCount = item.comments.filter(c => c.suggestedReply && c.status === 'pending').length;

  return (
    <button className={styles.card} data-active={active ? '1' : '0'} onClick={onClick}>
      <div className={styles.cardTop}>
        <span className={styles.laneDot} style={{ background: laneColor }} />
        <PlatformIcon platform={item.platform} />
        <span className={styles.ago}>{item.ago}</span>
      </div>

      <div className={styles.cardTitle}>{item.title}</div>
      <div className={styles.cardSummary}>{item.summary}</div>

      <div className={styles.cardStats}>
        <span className={styles.stat}>
          <Icon name="eye" size={12} color="var(--fg-4)" />
          {fmtNum(item.views)}
        </span>
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

export function Feed({ items: allItems = [], selectedId, onSelect, lanes = true }) {
  const [tab, setTab] = useState('brand');
  // News mode (lanes=false): one flat chronological list, no brand/competitor/niche tabs.
  const items = lanes ? allItems.filter(i => i.lane === tab) : allItems;

  const counts = {
    brand:      allItems.filter(i => i.lane === 'brand').length,
    competitor: allItems.filter(i => i.lane === 'competitor').length,
    niche:      allItems.filter(i => i.lane === 'niche').length,
  };

  return (
    <div className={styles.feed}>
      {lanes && (
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
      )}
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
