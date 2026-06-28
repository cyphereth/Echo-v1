// One post in a feed column. Side flag + author + time + clamped text + credibility dot.
import { CREDIBILITY, SIDE, agoStrShort } from '../api';
import styles from '../intel.module.css';

export function PostCard({ event, isNew }) {
  const cred = CREDIBILITY[event.credibility] || CREDIBILITY.unrated;
  const side = SIDE[event.side] || { label: '—', color: '#6A8499' };
  return (
    <div className={styles.postCard} data-new={isNew ? '1' : '0'}>
      <div className={styles.postMeta}>
        <span style={{ color: side.color }}>{side.label}</span>
        <span className={styles.postAuthor}>{event.author}</span>
        <span className={styles.postTime}>{agoStrShort(event.created_at)}</span>
        <span className={styles.postMatch} title={event.match_type === 'geo' ? 'по тексту' : 'по источнику'}>
          {event.match_type === 'geo' ? 'G' : 'S'}
        </span>
      </div>
      <div className={styles.postText}>{event.text}</div>
      <div className={styles.postCredRow}>
        <span className={styles.credDot} style={{ background: cred.color }} title={cred.label} />
        {event.url
          ? <a className={styles.postLink} href={event.url} target="_blank" rel="noreferrer">открыть</a>
          : null}
      </div>
    </div>
  );
}
