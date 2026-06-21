// News-specialized Feed — flat chronological list (no brand/competitor/niche lanes).
// Receives items pre-mapped from /news/inbox via NewsApp loadFeed.
import { Icon } from '../../../core/components/icons';
import styles from '../../../components/app/feed.module.css';

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

function NewsFeedCard({ item, active, onClick }) {
  return (
    <button className={styles.card} data-active={active ? '1' : '0'} onClick={onClick}>
      <div className={styles.cardTop}>
        <PlatformIcon platform={item.platform} />
        <span className={styles.ago}>{item.ago}</span>
      </div>

      <div className={styles.cardTitle}>{item.title}</div>
      <div className={styles.cardSummary}>{item.summary}</div>

      <div className={styles.cardStats}>
        {item.views > 0 && (
          <span className={styles.stat}>
            <Icon name="eye" size={12} color="var(--fg-4)" />
            {fmtNum(item.views)}
          </span>
        )}
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

// Flat feed — no lanes prop needed; always shows all items in order.
export function NewsFeed({ items = [], selectedId, onSelect }) {
  return (
    <div className={styles.feed}>
      <div className={styles.list}>
        {items.length === 0 && (
          <div style={{ padding: 24, color: 'var(--fg-3)', fontSize: 13 }}>
            Пока пусто — источники собираются.
          </div>
        )}
        {items.map(item => (
          <NewsFeedCard key={item.id} item={item}
            active={selectedId === item.id}
            onClick={() => onSelect(item.id)} />
        ))}
      </div>
    </div>
  );
}
