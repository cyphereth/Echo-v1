// Header notification bell: unread badge + dropdown of recent alerts + mute controls.
import { useState } from 'react';
import { Icon } from '../../../core/components/icons';
import { agoStrShort } from '../api';
import styles from '../intel.module.css';

export function AlertBell({ alerts = [], unreadCount = 0, onAck, onAckAll, onOpen,
                            onMute, muted = { stories: [], directions: [] }, onUnmute }) {
  const [open, setOpen] = useState(false);
  const [showMuted, setShowMuted] = useState(false);
  const mutedCount = (muted.stories?.length || 0) + (muted.directions?.length || 0);
  return (
    <div className={styles.bellWrap}>
      <button className={styles.bellBtn} onClick={() => setOpen(o => !o)} title="Сигналы">
        <Icon name="radio" size={15} />
        {unreadCount > 0 && <span className={styles.bellBadge}>{unreadCount > 99 ? '99+' : unreadCount}</span>}
      </button>
      {open && (
        <div className={styles.bellMenu}>
          <div className={styles.bellHead}>
            <span>Сигналы</span>
            {unreadCount > 0 && (
              <button className={styles.bellAckAll} onClick={() => onAckAll && onAckAll()}>
                Прочитать все
              </button>
            )}
          </div>
          {alerts.length === 0 ? (
            <div className={styles.bellEmpty}>Нет сигналов</div>
          ) : (
            alerts.slice(0, 30).map(a => (
              <div key={a.id} className={styles.bellItem} data-unread={a.acknowledged ? '0' : '1'}>
                <button className={styles.bellItemMain}
                        onClick={() => { onAck && onAck(a.id); onOpen && onOpen(a); setOpen(false); }}>
                  <span className={styles.bellItemMsg}>{a.message || a.title}</span>
                  <span className={styles.bellItemMeta}>{agoStrShort(a.at)}</span>
                </button>
                <button className={styles.bellMute}
                        title={a.scope === 'direction'
                          ? 'Не сигналить по этому направлению'
                          : 'Не сигналить по этому сюжету'}
                        onClick={() => onMute && onMute(a)}>🔕</button>
              </div>
            ))
          )}
          {mutedCount > 0 && (
            <div className={styles.bellMutedBox}>
              <button className={styles.bellMutedToggle} onClick={() => setShowMuted(v => !v)}>
                Заглушено ({mutedCount}) {showMuted ? '▾' : '▸'}
              </button>
              {showMuted && (
                <div className={styles.bellMutedList}>
                  {(muted.directions || []).map(d => (
                    <div key={`d${d.id}`} className={styles.bellMutedRow}>
                      <span className={styles.bellItemMsg}>📁 {d.name}</span>
                      <button className={styles.bellUnmute}
                              onClick={() => onUnmute && onUnmute('direction', d.id)}>вернуть</button>
                    </div>
                  ))}
                  {(muted.stories || []).map(st => (
                    <div key={`s${st.id}`} className={styles.bellMutedRow}>
                      <span className={styles.bellItemMsg}>{st.title}</span>
                      <button className={styles.bellUnmute}
                              onClick={() => onUnmute && onUnmute('story', st.id)}>вернуть</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
