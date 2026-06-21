// Shell — top-level app chrome. Owns mode (news | brand) and screen state.
// Mounts NewsApp or BrandApp depending on mode. Sidebar is a pure mode switch + nav.
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon } from '../core/components/icons';
import { clearToken } from '../core/api/client';
import { NewsApp } from '../features/news/NewsApp';
import { BrandApp } from '../features/brand/BrandApp';
import styles from '../components/app/shell.module.css';

// ── Primitives ────────────────────────────────────────────────────────────────

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

function ModeSwitch({ mode, onModeChange }) {
  const pill = (active) => ({
    flex: 1, padding: '6px 0', borderRadius: 'var(--r-md)', border: 'none',
    cursor: 'pointer', fontSize: 12, fontWeight: 700, fontFamily: 'var(--font-sans)',
    background: active ? 'var(--brand)' : 'var(--surface-3)',
    color: active ? '#fff' : 'var(--fg-3)', transition: 'all 0.15s',
  });
  return (
    <div style={{ display: 'flex', gap: 6, padding: '0 14px 12px' }}>
      <button style={pill(mode === 'news')}  onClick={() => onModeChange('news')}>Новости</button>
      <button style={pill(mode === 'brand')} onClick={() => onModeChange('brand')}>Бренд</button>
    </div>
  );
}

// ── Sidebar — mode switch + nav items for the active feature ──────────────────

function Sidebar({ mode, screen, setScreen, onModeChange, onLogout }) {
  return (
    <aside className={styles.sidebar}>
      <EchoLogo />
      <ModeSwitch mode={mode} onModeChange={onModeChange} />
      <nav className={styles.nav}>
        {mode === 'news' ? (
          <>
            <NavItem icon="activity" label="Сюжеты"    active={screen === 'stories'}  onClick={() => setScreen('stories')} />
            <NavItem icon="radio"    label="Лента"      active={screen === 'feed'}     onClick={() => setScreen('feed')} />
            <NavItem icon="zap"      label="Дайджесты"  active={screen === 'digests'}  onClick={() => setScreen('digests')} />
            <NavItem icon="search"   label="Источники"  active={screen === 'sources'}  onClick={() => setScreen('sources')} />
          </>
        ) : (
          <>
            <NavItem icon="radio"    label="Лента"      active={screen === 'feed'}      onClick={() => setScreen('feed')} />
            <NavItem icon="inbox"    label="Очередь"    active={screen === 'queue'}     onClick={() => setScreen('queue')} />
            <NavItem icon="pieChart" label="Аналитика"  active={screen === 'analytics'} onClick={() => setScreen('analytics')} />
            <NavItem icon="zap"      label="Дайджесты"  active={screen === 'digests'}   onClick={() => setScreen('digests')} />
            <NavItem icon="search"   label="Города"     active={screen === 'cities'}    onClick={() => setScreen('cities')} />
            <NavItem icon="settings" label="Настройки"  active={screen === 'settings'}  onClick={() => setScreen('settings')} />
          </>
        )}
      </nav>
      <div className={styles.sidebarBottom}>
        <div className={styles.brandChip} style={{ cursor: 'default' }}>
          <div className={styles.brandMonogram}>—</div>
          <div style={{ lineHeight: 1.25, flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-1)' }}>Echo</div>
            <div style={{ fontSize: 11, color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
              {mode === 'news' ? 'Режим новостей' : 'Режим бренда'}
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

// ── Shell — mode switch that mounts the active feature ────────────────────────

const NEWS_SCREENS = ['stories', 'feed', 'digests', 'sources'];
const BRAND_SCREENS = ['feed', 'queue', 'analytics', 'digests', 'cities', 'settings'];

export default function Shell() {
  const navigate = useNavigate();
  const [mode, setMode]     = useState('news');
  const [screen, setScreen] = useState('stories'); // news default

  function handleModeChange(next) {
    setMode(next);
    // Reset to the default first screen of the new mode
    setScreen(next === 'news' ? 'stories' : 'feed');
  }

  function handleLogout() {
    clearToken();
    navigate('/login');
  }

  return (
    <div className={styles.layout}>
      <Sidebar
        mode={mode}
        screen={screen}
        setScreen={setScreen}
        onModeChange={handleModeChange}
        onLogout={handleLogout}
      />
      {mode === 'news'
        ? <NewsApp screen={screen} setScreen={setScreen} />
        : <BrandApp screen={screen} setScreen={setScreen} />
      }
    </div>
  );
}

