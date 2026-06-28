import { useState, useRef, useCallback, useEffect } from 'react';
import { getToken } from '../../../core/api/client';

const ICON = { photo: '📷', video: '🎬', file: '📎' };
const TITLE = { photo: 'Прикреплено фото', video: 'Прикреплено видео', file: 'Прикреплён файл' };
const HOVER_DELAY = 200;

// Hover-превью медиа: лениво тянет картинку через fetch+Bearer, кладёт objectURL в <img>.
// Для file — просто иконка без поповера.
export default function MediaPreview({ kind, url, label }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState('idle'); // idle | loading | ready | error
  const [src, setSrc] = useState(null);
  const timer = useRef(null);
  const objUrl = useRef(null);

  const load = useCallback(async () => {
    if (state === 'ready' || state === 'loading') return;
    setState('loading');
    try {
      const token = getToken();
      const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) throw new Error(String(res.status));
      const blob = await res.blob();
      if (objUrl.current) URL.revokeObjectURL(objUrl.current);
      objUrl.current = URL.createObjectURL(blob);
      setSrc(objUrl.current);
      setState('ready');
    } catch {
      setState('error');
    }
  }, [url, state]);

  const onEnter = () => {
    if (kind === 'file') return;
    timer.current = setTimeout(() => { setOpen(true); load(); }, HOVER_DELAY);
  };
  const onLeave = () => { clearTimeout(timer.current); setOpen(false); };

  useEffect(() => () => {
    clearTimeout(timer.current);
    if (objUrl.current) URL.revokeObjectURL(objUrl.current);
  }, []);

  return (
    <span style={{ position: 'relative', marginRight: 4, cursor: kind === 'file' ? 'default' : 'zoom-in' }}
          title={TITLE[kind] || ''} onMouseEnter={onEnter} onMouseLeave={onLeave}>
      {ICON[kind] || '📎'}
      {open && kind !== 'file' && (
        <span style={{
          position: 'absolute', bottom: '120%', left: 0, zIndex: 50,
          background: '#0b0f14', border: '1px solid #1e2a36', borderRadius: 8,
          padding: 4, minWidth: 160, minHeight: 90, boxShadow: '0 8px 24px rgba(0,0,0,.5)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          {state === 'loading' && <span style={{ fontSize: 11, color: '#7c8b99' }}>загрузка…</span>}
          {state === 'error' && <span style={{ fontSize: 11, color: '#7c8b99' }}>превью недоступно ↗ TG</span>}
          {state === 'ready' && (
            <span style={{ position: 'relative', display: 'inline-flex' }}>
              <img src={src} alt={label || ''} style={{ maxWidth: 260, maxHeight: 200, borderRadius: 6, display: 'block' }} />
              {kind === 'video' && (
                <span style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
                               justifyContent: 'center', fontSize: 28, color: '#fff', textShadow: '0 2px 6px #000' }}>▶</span>
              )}
            </span>
          )}
        </span>
      )}
    </span>
  );
}
