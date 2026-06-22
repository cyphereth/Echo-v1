// News Sources — управление источниками темы (TG-каналы/поиск/веб).
// Канон спеки 2026-06-18-news-redesign: таблица с объёмом упоминаний,
// добавить канал, удалить. Под дизайн-систему: карточка-список, Button/Icon/Eyebrow.
// API: GET/POST/DELETE /topics/{id}/sources.
import { useEffect, useState } from 'react';
import { Icon } from '../../../core/components/icons';
import { Button } from '../../../core/components/ui';
import * as api from '../api';
import styles from '../../../components/app/sources.module.css';

const KIND_LABEL = { channel: 'TG-канал', global: 'TG-поиск', web: 'Веб' };

export function NewsSourcesScreen({ topicId, topicName }) {
  const [rows, setRows]     = useState([]);
  const [val, setVal]       = useState('');
  const [busy, setBusy]     = useState(false);
  const [err, setErr]       = useState(null);

  const load = () => {
    if (!topicId) { setRows([]); return; }
    api.getTopicSources(topicId).then(setRows).catch(() => setRows([]));
  };
  useEffect(load, [topicId]);

  if (!topicId) {
    return <div className={styles.wrap}><div className={styles.placeholder}>Выберите тему для просмотра источников.</div></div>;
  }

  const add = async () => {
    const h = val.trim();
    if (!h) return;
    setBusy(true); setErr(null);
    try {
      await api.addTopicSource(topicId, h);
      setVal('');
      load();
    } catch (e) {
      setErr(String(e.message || e).includes('409') ? 'Уже добавлен' : 'Не удалось добавить');
    } finally {
      setBusy(false);
    }
  };
  const del = async (id) => {
    try { await api.deleteTopicSource(topicId, id); load(); } catch { /* ignore */ }
  };

  const totalMentions = rows.reduce((s, r) => s + (r.mention_count || 0), 0);

  return (
    <div className={styles.wrap}>
      <div className={styles.inner}>
        <div className={styles.intro}>
          <h2>Источники</h2>
          <p>
            Telegram-каналы и веб-домены, с которых Echo Radar собирает упоминания
            по теме <b style={{ color: 'var(--fg-1)' }}>{topicName || ''}</b>.
            Чем больше независимых источников — тем выше доверие к сюжету.
          </p>
        </div>

        <div className={styles.addBar}>
          <div className={styles.addInput}>
            <Icon name="search" size={15} color="var(--fg-3)" />
            <input
              value={val}
              onChange={e => setVal(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && add()}
              placeholder="@канал — добавить источник"
            />
          </div>
          <Button variant="primary" icon="plus" onClick={add} disabled={busy}>
            {busy ? 'Добавляю…' : 'Добавить'}
          </Button>
        </div>
        {err && <div className={styles.err}>{err}</div>}

        <div className={styles.list}>
          <div className={styles.listHead}>
            <span className={styles.listHeadTitle}>
              <Icon name="radio" size={16} color="var(--brand-bright)" />
              Источники
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700, color: 'var(--brand-bright)', background: 'var(--brand-ghost)', padding: '2px 8px', borderRadius: 'var(--r-pill)' }}>
                {rows.length}
              </span>
              <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--fg-3)' }}>
                {totalMentions} упоминаний всего
              </span>
            </span>
          </div>
          {rows.length === 0 ? (
            <div className={styles.empty}>
              Источников пока нет. Добавьте Telegram-канал выше —
              радар начнёт слушать его по теме.
            </div>
          ) : (
            rows.map((r, i) => (
              <div key={`${r.kind}-${r.handle}-${i}`} className={styles.row}>
                <span className={styles.kindPill} data-kind={r.kind}>
                  {KIND_LABEL[r.kind] || r.kind}
                </span>
                <span className={styles.handle}>
                  {r.handle}
                  {r.title && r.title !== 'manual' && r.title !== 'seed' && r.title !== 'similar' && (
                    <span className={styles.handleTitle}> · {r.title}</span>
                  )}
                </span>
                <span className={styles.count}>{r.mention_count || 0}</span>
                {r.id != null && (
                  <button className={styles.delBtn} onClick={() => del(r.id)} title="Удалить источник">
                    <Icon name="x" size={14} color="var(--fg-4)" />
                  </button>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
