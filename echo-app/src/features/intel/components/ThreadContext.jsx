// Reply-thread context for a mention. Lazy-loads /intel/mention/{id}/context on
// first expand and renders the reply chain + sibling replies inline. Shared by the
// home feed («Лента событий») and the story-detail events list.
import { useState } from 'react';
import { intelApi } from '../api';

export function ThreadContext({ mentionId }) {
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

  const borderStyle = { borderLeft: '2px solid #2BB3C7', paddingLeft: 8, margin: '4px 0' };
  const hasCtx = ctx && ((ctx.reply_chain?.length || 0) + (ctx.siblings?.length || 0)) > 0;

  return (
    <div style={{ marginBottom: 4 }}>
      <button
        onClick={(ev) => { ev.stopPropagation(); toggle(); }}
        style={{ background: 'none', border: 'none', color: '#4A6378', fontSize: 10,
                 fontFamily: 'var(--font-mono)', cursor: 'pointer', padding: '0 0 2px' }}>
        {loading ? '…' : open ? '↓ свернуть тред' : '↑ в ответ на'}
      </button>
      {open && ctx && (
        hasCtx ? (
          <div style={borderStyle}>
            {[...(ctx.reply_chain || [])].reverse().map((p, i) => (
              <div key={p.tg_msg_id} style={{ color: '#4A6378', fontSize: 11, marginBottom: 2,
                                              paddingLeft: i * 8 }}>
                <span style={{ color: '#3A5368', marginRight: 4 }}>{p.author}</span>
                {p.text}
              </div>
            ))}
            {(ctx.siblings || []).map(s => (
              <div key={s.tg_msg_id} style={{ color: '#4A6378', fontSize: 11, marginBottom: 2,
                                              paddingLeft: (ctx.reply_chain?.length || 0) * 8 }}>
                <span style={{ color: '#3A5368', marginRight: 4 }}>{s.author}</span>
                {s.text}
              </div>
            ))}
          </div>
        ) : (
          <div style={{ ...borderStyle, color: '#4A6378', fontSize: 11 }}>
            Родительское сообщение ещё не подгружено.
          </div>
        )
      )}
    </div>
  );
}
