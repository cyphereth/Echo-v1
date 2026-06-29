// Reply-thread context for a mention. Lazy-loads /intel/mention/{id}/context on
// first expand and renders the reply chain + sibling replies inline. Shared by the
// home feed («Лента событий») and the story-detail events list.
import { useState } from 'react';
import { intelApi } from '../api';
import MediaPreview from './MediaPreview';

export function ThreadContext({ mentionId, compact = false }) {
  const [open, setOpen] = useState(false);
  const [ctx, setCtx] = useState(null);
  const [loading, setLoading] = useState(false);

  function toggle() {
    if (open) { setOpen(false); return; }
    if (ctx) { setOpen(true); return; }
    setLoading(true);
    intelApi.mentionContext(mentionId)
      .then(data => { setCtx(data); setOpen(true); })
      .catch(() => { setCtx({ reply_chain: [], siblings: [] }); setOpen(true); })
      .finally(() => setLoading(false));
  }

  // Подложка + светлый текст: в треде сообщения должны читаться так же легко, как
  // основная лента (раньше были тускло-серыми #4A6378 на тёмном фоне).
  const borderStyle = {
    borderLeft: '2px solid #2BB3C7', padding: compact ? '4px 8px' : '6px 10px', margin: '4px 0',
    background: 'rgba(43, 179, 199, 0.07)', borderRadius: 4,
  };
  const msgStyle = { color: '#CBD9E3', fontSize: compact ? 10.5 : 12, lineHeight: 1.4, marginBottom: compact ? 3 : 4 };
  const authorStyle = { color: '#5FB6C7', fontWeight: 600, marginRight: 4 };
  const hasCtx = ctx && ((ctx.reply_chain?.length || 0) + (ctx.siblings?.length || 0)) > 0;

  return (
    <div style={{ marginBottom: 4 }}>
      <button
        onClick={(ev) => { ev.stopPropagation(); toggle(); }}
        style={{ background: 'none', border: 'none', color: '#4A6378', fontSize: compact ? 9 : 10,
                 fontFamily: 'var(--font-mono)', cursor: 'pointer', padding: '0 0 2px' }}>
        {loading ? '…' : open ? '↓ свернуть тред' : '↑ в ответ на'}
      </button>
      {open && ctx && (
        hasCtx ? (
          <div style={borderStyle}>
            {[...(ctx.reply_chain || [])].reverse().map((p, i) => (
              <div key={p.tg_msg_id} style={{ ...msgStyle, paddingLeft: i * 8 }}>
                <span style={authorStyle}>{p.author}</span>
                {p.media && (
                  <MediaPreview kind={p.media}
                    url={`/intel/mention/${mentionId}/parent-media/${p.tg_msg_id}`}
                    label={p.text} />
                )}
                {p.text}
              </div>
            ))}
            {(ctx.siblings || []).map(s => (
              <div key={s.tg_msg_id} style={{ ...msgStyle,
                                              paddingLeft: (ctx.reply_chain?.length || 0) * 8 }}>
                <span style={authorStyle}>{s.author}</span>
                {s.text}
              </div>
            ))}
          </div>
        ) : (
          <div style={{ ...borderStyle, color: '#8FA6B5', fontSize: compact ? 10.5 : 12 }}>
            Родительское сообщение ещё не подгружено.
          </div>
        )
      )}
    </div>
  );
}
