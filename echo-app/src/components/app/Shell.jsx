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

export function Sidebar({
  screen, setScreen, brand,
  brands = [], activeBrandId, onSelectBrand, onNewBrand, onLogout,
}) {
  const negCount = 3;
  const [menuOpen, setMenuOpen] = useState(false);

  const menuItem = {
    display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left',
    padding: '8px 10px', borderRadius: 'var(--r-sm)', fontSize: 13, color: 'var(--fg-2)',
    background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'var(--font-sans)',
  };

  return (
    <aside className={styles.sidebar}>
      <EchoLogo />
      <nav className={styles.nav}>
        <NavItem icon="radio"       label="Лента"      active={screen === 'feed'}      badge={negCount} onClick={() => setScreen('feed')} />
        <NavItem icon="inbox"       label="Очередь"    active={screen === 'queue'}     onClick={() => setScreen('queue')} />
        <NavItem icon="pieChart"    label="Аналитика"  active={screen === 'analytics'} onClick={() => setScreen('analytics')} />
        <NavItem icon="settings"    label="Настройки"  active={screen === 'settings'}  onClick={() => setScreen('settings')} />
      </nav>
      <div className={styles.sidebarBottom} style={{ position: 'relative' }}>
        {menuOpen && (
          <>
            <div onClick={() => setMenuOpen(false)}
              style={{ position: 'fixed', inset: 0, zIndex: 10 }} />
            <div style={{
              position: 'absolute', bottom: 'calc(100% + 8px)', left: 0, right: 0, zIndex: 11,
              background: 'var(--surface-2)', border: '1px solid var(--line-2)',
              borderRadius: 'var(--r-md)', padding: 6, boxShadow: '0 8px 28px rgba(0,0,0,0.5)',
            }}>
              {brands.map(b => (
                <button key={b.id} style={{
                  ...menuItem,
                  background: b.id === activeBrandId ? 'var(--surface-3)' : 'none',
                  color: b.id === activeBrandId ? 'var(--fg-1)' : 'var(--fg-2)',
                }} onClick={() => { onSelectBrand?.(b.id); setMenuOpen(false); }}>
                  <div className={styles.brandMonogram} style={{ width: 22, height: 22, fontSize: 10 }}>
                    {b.name?.slice(0, 2).toUpperCase()}
                  </div>
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{b.name}</span>
                  {b.id === activeBrandId && <Icon name="check" size={13} color="var(--brand-bright)" />}
                </button>
              ))}
              {brands.length > 0 && <div style={{ height: 1, background: 'var(--line)', margin: '6px 4px' }} />}
              <button style={menuItem} onClick={() => { onNewBrand?.(); setMenuOpen(false); }}>
                <Icon name="plus" size={14} color="var(--fg-3)" /> Новый бренд
              </button>
              <button style={{ ...menuItem, color: 'var(--neg)' }} onClick={() => { onLogout?.(); setMenuOpen(false); }}>
                <Icon name="x" size={14} color="var(--neg)" /> Выйти
              </button>
            </div>
          </>
        )}
        <button className={styles.brandChip} onClick={() => setMenuOpen(o => !o)}>
          <div className={styles.brandMonogram}>
            {brand?.name?.slice(0, 2).toUpperCase() ?? 'PP'}
          </div>
          <div style={{ lineHeight: 1.25, flex: 1, minWidth: 0, textAlign: 'left' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {brand?.name ?? '—'}
            </div>
            <div style={{ fontSize: 11, color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
              {brands.length > 1 ? `${brands.length} бренда` : (brand?.niche ?? '')}
            </div>
          </div>
          <Icon name="chevronDown" size={13} color="var(--fg-4)" />
        </button>
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
