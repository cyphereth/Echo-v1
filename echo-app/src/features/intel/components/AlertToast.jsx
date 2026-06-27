// Corner toast stack for incoming alerts. Auto-dismisses each after 8s.
import { useEffect } from 'react';
import { Icon } from '../../../core/components/icons';
import styles from '../intel.module.css';

function Toast({ alert, onDismiss, onOpen }) {
  useEffect(() => {
    const t = setTimeout(() => onDismiss(alert.id), 8000);
    return () => clearTimeout(t);
  }, [alert.id, onDismiss]);
  return (
    <div className={styles.toast} onClick={() => onOpen(alert)}>
      <Icon name="radio" size={14} />
      <div className={styles.toastBody}>
        <div className={styles.toastTitle}>{alert.title || 'Сигнал'}</div>
        <div className={styles.toastMsg}>{alert.message}</div>
      </div>
      <button className={styles.toastClose} onClick={(e) => { e.stopPropagation(); onDismiss(alert.id); }}>
        <Icon name="x" size={12} />
      </button>
    </div>
  );
}

export function AlertToast({ toasts = [], onDismiss, onOpen }) {
  if (!toasts.length) return null;
  return (
    <div className={styles.toastStack}>
      {toasts.slice(-4).map(t => (
        <Toast key={t.id} alert={t} onDismiss={onDismiss} onOpen={onOpen} />
      ))}
    </div>
  );
}
