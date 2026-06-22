// TopBar + ScopeBar — общие для обоих режимов. Канон: project/ui_kits/app/shell.jsx.
// Мёртвый дублирующий Sidebar удалён — единый источник истины теперь src/app/Shell.jsx.
import { Icon } from '../../core/components/icons';
import styles from './shell.module.css';

// ── TopBar ──────────────────────────────────────────────────────────────────
// Принимает опциональный brand-селектор (имя+подзаголовок) или просто title/sub.
export function TopBar({ title, sub, brand, onSearch, searchText, onSearchChange, actions, children }) {
  return (
    <header className={styles.topbar}>
      {brand ? (
        <div className={styles.brandSel}>
          <div className={styles.brandMonogram}>
            {(brand.name || '?').slice(0, 1).toUpperCase()}
          </div>
          <div style={{ lineHeight: 1.2 }}>
            <div className={styles.brandSelName}>{brand.name}</div>
            {brand.sub && <div className={styles.brandSelSub}>{brand.sub}</div>}
          </div>
        </div>
      ) : (
        <div>
          <div className={styles.topbarTitle}>{title}</div>
          {sub && <div className={styles.topbarSub}>{sub}</div>}
        </div>
      )}
      <div className={styles.topgrow} />
      {actions}
      {children}
      <div className={styles.searchBox}>
        <Icon name="search" size={14} color="var(--fg-3)" />
        <input
          value={searchText || ''}
          onChange={onSearchChange}
          onKeyDown={(e) => { if (e.key === 'Enter' && onSearch) onSearch(searchText); }}
          placeholder="Поиск упоминаний…"
        />
      </div>
      <button className={styles.icBtn} title="Уведомления">
        <Icon name="bell" size={17} color="var(--fg-2)" />
        <span className={styles.bellDot} />
      </button>
    </header>
  );
}

// ── ScopeBar ────────────────────────────────────────────────────────────────
// 46px-полоса с live-счётчиками: сигналов / залетает / растёт.
// live = всего активных; crit = severity≥75; rise = 45≤severity<75.
export function ScopeBar({ live = 0, critical = 0, rising = 0, syncText }) {
  return (
    <div className={styles.scope}>
      <div className={styles.scopeLive}>
        <span className={styles.pulse} style={{ width: 9, height: 9, borderRadius: '50%', background: 'var(--sev-calm)', flexShrink: 0, animation: 'erpulse 2.4s var(--ease-in-out) infinite' }} />
        <span>В эфире</span>
      </div>
      <div className={styles.scopeDiv} />
      <div className={styles.scopeStat}>
        <span className={styles.scopeStatNum}>{live}</span>
        <span className={styles.scopeStatLabel}>сигналов</span>
      </div>
      <div className={styles.scopeStat}>
        <span className={styles.scopeStatNum} style={{ color: '#FF7A87' }}>{critical}</span>
        <span className={styles.scopeStatLabel}>залетает</span>
      </div>
      <div className={styles.scopeStat}>
        <span className={styles.scopeStatNum} style={{ color: '#FFC871' }}>{rising}</span>
        <span className={styles.scopeStatLabel}>растёт</span>
      </div>
      {syncText && <div className={styles.scopeRight}>{syncText}</div>}
    </div>
  );
}
