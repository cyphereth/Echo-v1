// One column: header (name + count + ✕) + scrollable list of PostCards.
import { PostCard } from './PostCard';
import styles from '../intel.module.css';

export function FeedColumn({ direction, events, onRemove }) {
  return (
    <div className={styles.feedColumn}>
      <div className={styles.feedColumnHead}>
        <span className={styles.feedColumnName}>{direction.name}</span>
        <span className={styles.feedColumnCount}>{events.length}</span>
        <button className={styles.feedColumnX} title="убрать колонку" onClick={onRemove}>✕</button>
      </div>
      <div className={styles.feedColumnBody}>
        {events.length === 0
          ? <div className={styles.feedColumnEmpty}>нет событий в окне</div>
          : events.map((e) => <PostCard key={e.id} event={e} isNew={e._new} />)}
      </div>
    </div>
  );
}
