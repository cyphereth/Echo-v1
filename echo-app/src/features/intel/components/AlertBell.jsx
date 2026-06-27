// Header notification bell: unread badge + dropdown of recent alerts.
import { useState } from 'react';
import { Icon } from '../../../core/components/icons';
import { agoStrShort } from '../api';
import styles from '../intel.module.css';

export function AlertBell({ alerts = [], unreadCount = 0, onAck, onAckAll, onOpen }) {
  const [open, setOpen] = useState(false);
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
              <button key={a.id} className={styles.bellItem} data-unread={a.acknowledged ? '0' : '1'}
                      onClick={() => { onAck && onAck(a.id); onOpen && onOpen(a); setOpen(false); }}>
                <span className={styles.bellItemMsg}>{a.message || a.title}</span>
                <span className={styles.bellItemMeta}>{agoStrShort(a.at)}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
