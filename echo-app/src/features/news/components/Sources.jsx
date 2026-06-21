// News-specialized Sources panel — always topic-scoped (no brand path).
// Wired to: GET/POST/DELETE /topics/{id}/sources via features/news/api.js
import { useEffect, useState } from 'react';
import * as api from '../api';

const KIND_LABEL = { channel: 'TG-канал', global: 'TG-поиск', web: 'Веб' };

// Accepts topicId directly — no scope object.
export function NewsSourcesScreen({ topicId }) {
  const [rows, setRows] = useState([]);
  const [val, setVal] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const load = () => {
    if (!topicId) { setRows([]); return; }
    api.getTopicSources(topicId).then(setRows).catch(() => setRows([]));
  };
  useEffect(load, [topicId]);

  if (!topicId) {
    return <div style={{ padding: 24, color: 'var(--fg-3)', fontSize: 14 }}>
      Выберите тему для просмотра источников.
    </div>;
  }

  const add = async () => {
    const h = val.trim();
    if (!h) return;
    setBusy(true); setErr(null);
    try { await api.addTopicSource(topicId, h); setVal(''); load(); }
    catch (e) { setErr(String(e.message || e).includes('409') ? 'Уже добавлен' : 'Не удалось добавить'); }
    finally { setBusy(false); }
  };
  const del = async (id) => { try { await api.deleteTopicSource(topicId, id); load(); } catch { /* ignore */ } };

  return (
    <div style={{ padding: 20, overflow: 'auto', width: '100%' }}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, maxWidth: 480 }}>
        <input
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          placeholder="@канал — добавить источник"
          style={{ flex: 1, padding: '8px 12px', borderRadius: 'var(--r-md)',
                   border: '1px solid var(--border)', background: 'var(--surface-2)',
                   color: 'var(--fg-1)', fontSize: 13, outline: 'none' }}
        />
        <button onClick={add} disabled={busy}
          style={{ padding: '8px 16px', borderRadius: 'var(--r-md)', border: 'none',
                   background: 'var(--brand)', color: '#fff', fontWeight: 600, fontSize: 13,
                   cursor: busy ? 'default' : 'pointer' }}>
          {busy ? '…' : 'Добавить'}
        </button>
      </div>
      {err && <div style={{ color: '#ef4444', fontSize: 12, marginBottom: 10 }}>{err}</div>}

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ color: 'var(--fg-3)', textAlign: 'left' }}>
            <th style={{ padding: '6px 8px', fontWeight: 600 }}>Источник</th>
            <th style={{ padding: '6px 8px', fontWeight: 600 }}>Тип</th>
            <th style={{ padding: '6px 8px', fontWeight: 600, textAlign: 'right' }}>Постов</th>
            <th style={{ padding: '6px 8px' }} />
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={4} style={{ padding: 16, color: 'var(--fg-3)' }}>Источников пока нет.</td></tr>
          )}
          {rows.map((r, i) => (
            <tr key={`${r.kind}-${r.handle}-${i}`} style={{ borderTop: '1px solid var(--border)' }}>
              <td style={{ padding: '8px', fontFamily: 'var(--font-mono)' }}>
                {r.handle}{r.title && r.title !== 'manual' && r.title !== 'seed' && r.title !== 'similar'
                  ? <span style={{ color: 'var(--fg-3)' }}> · {r.title}</span> : null}
              </td>
              <td style={{ padding: '8px', color: 'var(--fg-3)' }}>{KIND_LABEL[r.kind] || r.kind}</td>
              <td style={{ padding: '8px', textAlign: 'right' }}>{r.mention_count}</td>
              <td style={{ padding: '8px', textAlign: 'right' }}>
                {r.id != null && (
                  <button onClick={() => del(r.id)} title="Удалить источник"
                    style={{ background: 'none', border: 'none', cursor: 'pointer',
                             color: 'var(--fg-4)', fontSize: 15 }}>✕</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
