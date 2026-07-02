// One post in a feed column. Полная идентичность строке «Ленты событий» из
// Ситуационного центра (IntelHome): флаг стороны + медиа + полный текст +
// 📍местоположение + автор·направление + repost-счётчик + ✓ + ссылка TG +
// контекст треда + время + ✕ удаление (в спам). Стили — те же классы eventRow*,
// поэтому колонка выглядит так же, как ситуационная лента.
import { useState } from 'react';
import { SIDE, DIRECTION_NAMES, agoStrShort } from '../api';
import { ThreadContext } from './ThreadContext';
import MediaPreview from './MediaPreview';
import styles from '../intel.module.css';

const LONG_TEXT = 240;
const cleanText = (t) => (t || '').replace(/\s+/g, ' ').trim();

export function PostCard({ event, isNew, onSpam, expandThreads = false, threadData = null }) {
  const [threadOpen, setThreadOpen] = useState(false);
  const sd = SIDE[event.side] || SIDE.ru;
  const dups = event._dups || 1;
  const text = cleanText(event.text);
  const textClass = text.length > LONG_TEXT
    ? `${styles.eventText} ${styles.eventTextLong}`
    : styles.eventText;
  return (
    <div className={isNew ? `${styles.eventRow} ${styles.eventRowNew}` : styles.eventRow}>
      <span className={styles.eventSide} style={{ color: sd.color, background: sd.color + '1A' }}>
        {sd.label}
      </span>
      <div className={styles.eventBody}>
        <div className={textClass}>
          {event.media && (
            <MediaPreview kind={event.media} url={`/intel/mention/${event.id}/media`} label={event.text} />
          )}
          {text}
        </div>
        <div className={styles.eventMeta}>
          {event.subject && <span style={{ color: '#57D2E2' }}>📍 {event.subject} · </span>}
          {event.author} · {DIRECTION_NAMES[event.direction]?.split(' ')[0] || event.direction}
          {dups > 1 ? ` · ${dups} канал.` : ''}
          {event.verified ? ' · ✓' : ''}
          {event.url && (
            <> · <a href={event.url} target="_blank" rel="noopener noreferrer"
                   onClick={ev => ev.stopPropagation()}
                   style={{ color: '#57D2E2', textDecoration: 'none' }}>↗ TG</a></>
          )}
        </div>
        {event.is_reply && <ThreadContext mentionId={event.id} compact forceOpen={expandThreads} data={threadData} />}
        {event._thread?.length > 0 && (
          <div className={styles.threadLive}>
            <button type="button"
                    className={styles.threadLiveHead}
                    onClick={(ev) => { ev.stopPropagation(); setThreadOpen(o => !o); }}
                    title={threadOpen ? 'Свернуть ответы' : 'Показать ответы'}>
              🧵 {threadOpen ? '▾' : '▸'} +{event._thread.length} в треде
            </button>
            {threadOpen && event._thread.map((r, i) => (
              <div key={r.id}
                   className={i === event._thread.length - 1
                     ? `${styles.threadLiveMsg} ${styles.threadLiveMsgNew}`
                     : styles.threadLiveMsg}>
                <span className={styles.threadLiveAuthor}>{r.author}</span>{cleanText(r.text)}
              </div>
            ))}
          </div>
        )}
      </div>
      <span className={styles.eventTime}>{agoStrShort(event.created_at)}</span>
      {onSpam && (
        <button
          className={styles.eventSpam}
          onClick={(ev) => onSpam(event, ev)}
          title="В спам (скрыть и запомнить как мусор)"
        >✕</button>
      )}
    </div>
  );
}
