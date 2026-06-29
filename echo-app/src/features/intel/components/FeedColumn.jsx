// One column: header (name + count + LIVE/ПАУЗА + ✕) + scrollable list of PostCards.
// Наведение курсора замораживает колонку (как ситуационная лента): onEnter/onLeave
// поднимаются в IntelFeed, который перестаёт вливать новые события в эту колонку.
// Повторы одного поста по разным каналам схлопываются в одну строку по content-sig.
import { useMemo } from 'react';
import { PostCard } from './PostCard';
import styles from '../intel.module.css';

export function FeedColumn({ direction, events, paused, newCount, onEnter, onLeave, onRemove, hiddenIds, onSpam }) {
  // Схлопываем дубль-репосты (один sig → одна строка, newest) и убираем скрытые.
  const feed = useMemo(() => {
    const out = [];
    const bySig = new Map();
    for (const e of events) {
      if (hiddenIds?.has(e.id)) continue;
      const key = e.sig || `id:${e.id}`;
      if (bySig.has(key)) { out[bySig.get(key)]._dups += 1; continue; }
      bySig.set(key, out.length);
      out.push({ ...e, _dups: 1 });
    }
    return out;
  }, [events, hiddenIds]);

  return (
    <div className={styles.feedColumn} onMouseEnter={onEnter} onMouseLeave={onLeave}>
      <div className={styles.feedColumnHead}>
        <span className={styles.feedColumnName}>{direction.name}</span>
        <span className={styles.feedColumnCount}>{feed.length}</span>
        {paused ? (
          <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 10, color: '#FFB23E', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            {newCount > 0 && <span style={{ fontWeight: 700 }}>+{newCount}</span>}❚❚ ПАУЗА
          </span>
        ) : (
          <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 10, color: '#34D8A0', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#34D8A0', animation: 'erpulse 2.4s var(--ease-in-out) infinite' }} />LIVE
          </span>
        )}
        <button className={styles.feedColumnX} title="убрать колонку" onClick={onRemove}>✕</button>
      </div>
      <div className={styles.feedColumnBody}>
        {feed.length === 0
          ? <div className={styles.feedColumnEmpty}>нет событий в окне</div>
          : feed.map((e) => <PostCard key={e.id} event={e} isNew={e._new} onSpam={onSpam} />)}
      </div>
    </div>
  );
}
