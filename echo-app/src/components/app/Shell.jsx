import { useState } from 'react';
import { Icon } from '../shared/icons';
import styles from './shell.module.css';

function NavItem({ icon, label, active, badge, onClick }) {
  return (
    <button className={styles.navItem} data-active={active ? '1' : '0'} onClick={onClick}>
      <Icon name={icon} size={16} />
      <span style={{ flex: 1 }}>{label}</span>
      {badge > 0 && <span className={styles.navBadge}>{badge}</span>}
    </button>
  );
}

function EchoLogo() {
  return (
    <div className={styles.logo}>
      <div className={styles.logoMark}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round">
          <path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5M12 12h.01" />
        </svg>
      </div>
      <span className={styles.logoName}>Echo</span>
    </div>
  );
}

export function Sidebar({ screen, setScreen, brand, onLogout }) {
  const negCount = 3;

  return (
    <aside className={styles.sidebar}>
      <EchoLogo />
      <nav className={styles.nav}>
        <NavItem icon="radio"    label="Лента"     active={screen === 'feed'}      badge={negCount} onClick={() => setScreen('feed')} />
        <NavItem icon="inbox"    label="Очередь"   active={screen === 'queue'}     onClick={() => setScreen('queue')} />
        <NavItem icon="pieChart" label="Аналитика" active={screen === 'analytics'} onClick={() => setScreen('analytics')} />
        <NavItem icon="settings" label="Настройки" active={screen === 'settings'}  onClick={() => setScreen('settings')} />
      </nav>
      <div className={styles.sidebarBottom}>
        <div className={styles.brandChip} style={{ cursor: 'default' }}>
          <div className={styles.brandMonogram}>
            {brand?.name?.slice(0, 2).toUpperCase() ?? '—'}
          </div>
          <div style={{ lineHeight: 1.25, flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {brand?.name ?? '—'}
            </div>
            <div style={{ fontSize: 11, color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
              {brand?.niche ?? ''}
            </div>
          </div>
          <button
            onClick={onLogout}
            title="Выйти"
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: 'var(--fg-4)' }}
          >
            <Icon name="x" size={13} color="var(--fg-4)" />
          </button>
        </div>
      </div>
    </aside>
  );
}

export function TopBar({ title, sub, children }) {
  return (
    <header className={styles.topbar}>
      <div>
        <div className={styles.topbarTitle}>{title}</div>
        {sub && <div className={styles.topbarSub}>{sub}</div>}
      </div>
      {children}
      <div className={styles.searchBox}>
        <Icon name="search" size={14} color="var(--fg-3)" />
        <span style={{ fontSize: 13, color: 'var(--fg-3)' }}>Поиск упоминаний…</span>
      </div>
      <button className={styles.icBtn} style={{ position: 'relative' }}>
        <Icon name="bell" size={17} color="var(--fg-2)" />
        <span className={styles.bellDot} />
      </button>
    </header>
  );
}
