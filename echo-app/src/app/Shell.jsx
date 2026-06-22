// Shell — top-level app chrome. Owns mode (news | brand) and screen state.
// Mounts NewsApp or BrandApp depending on mode. Канон layout:
// project/ui_kits/app/styles.css — 232px sidebar | main (topbar + scope + workspace).
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon } from '../core/components/icons';
import { EchoWordmark } from '../core/components/icons';
import { clearToken } from '../core/api/client';
import { NewsApp } from '../features/news/NewsApp';
import { BrandApp } from '../features/brand/BrandApp';
import { IntelApp } from '../features/intel/IntelApp';
import styles from '../components/app/shell.module.css';

// ── Sidebar nav item ────────────────────────────────────────────────────────
function NavItem({ icon, label, active, badge, onClick }) {
  return (
    <button className={styles.navItem} data-active={active ? '1' : '0'} onClick={onClick}>
      <Icon name={icon} size={16} />
      <span style={{ flex: 1 }}>{label}</span>
      {badge > 0 && <span className={styles.navBadge}>{badge}</span>}
    </button>
  );
}

// ── Sidebar ─────────────────────────────────────────────────────────────────
function Sidebar({ mode, screen, setScreen, onModeChange, onLogout }) {
  return (
    <aside className={styles.sidebar}>
      <div className={styles.logo}>
        <EchoWordmark size={22} />
      </div>
      <div className={styles.modeSwitch}>
        <button className={styles.modePill} data-active={mode === 'news' ? '1' : '0'} onClick={() => onModeChange('news')}>Новости</button>
        <button className={styles.modePill} data-active={mode === 'brand' ? '1' : '0'} onClick={() => onModeChange('brand')}>Бренд</button>
        <button className={styles.modePill} data-active={mode === 'intel' ? '1' : '0'} onClick={() => onModeChange('intel')}>Разведка</button>
      </div>
      <nav className={styles.nav}>
        {mode === 'news' ? (
          <>
            <NavItem icon="activity" label="Сюжеты"   active={screen === 'stories'} onClick={() => setScreen('stories')} />
            <NavItem icon="radio"    label="Лента"    active={screen === 'feed'}    onClick={() => setScreen('feed')} />
            <NavItem icon="zap"      label="Дайджесты" active={screen === 'digests'} onClick={() => setScreen('digests')} />
            <NavItem icon="search"   label="Источники" active={screen === 'sources'} onClick={() => setScreen('sources')} />
          </>
        ) : (
          <>
            <NavItem icon="bar3"     label="Обзор"     active={screen === 'overview'}  onClick={() => setScreen('overview')} />
            <NavItem icon="inbox"    label="Лента"     active={screen === 'feed'}      onClick={() => setScreen('feed')} />
            <NavItem icon="radio"    label="Зонды"     active={screen === 'probes'}    onClick={() => setScreen('probes')} />
            <NavItem icon="inboxTray" label="Очередь"  active={screen === 'queue'}     onClick={() => setScreen('queue')} />
            <NavItem icon="activity" label="Сюжеты"    active={screen === 'stories'}   onClick={() => setScreen('stories')} />
            <NavItem icon="pieChart" label="Аналитика" active={screen === 'analytics'} onClick={() => setScreen('analytics')} />
            <NavItem icon="zap"      label="Дайджесты" active={screen === 'digests'}   onClick={() => setScreen('digests')} />
            <NavItem icon="search"   label="Города"    active={screen === 'cities'}    onClick={() => setScreen('cities')} />
            <NavItem icon="settings" label="Настройки" active={screen === 'settings'}  onClick={() => setScreen('settings')} />
          </>
        )}
      </nav>
      <div className={styles.sidebarBottom}>
        <div className={styles.status}>
          <span className={styles.pulse} />
          <span className={styles.statusLabel}>В эфире</span>
        </div>
        <div className={styles.brandChip}>
          <div className={styles.brandMonogram}>E</div>
          <div style={{ lineHeight: 1.25, flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-1)' }}>Echo</div>
            <div style={{ fontSize: 11, color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
              {mode === 'news' ? 'режим новостей' : 'режим бренда'}
            </div>
          </div>
          <button onClick={onLogout} title="Выйти" className={styles.logoutBtn}>
            <Icon name="logout" size={15} color="var(--fg-4)" />
          </button>
        </div>
      </div>
    </aside>
  );
}

// ── Shell — mode switch that mounts the active feature ──────────────────────
export default function Shell() {
  const navigate = useNavigate();
  const [mode, setMode]     = useState('news');
  const [screen, setScreen] = useState('stories'); // news default — «Сюжеты»

  function handleModeChange(next) {
    setMode(next);
    setScreen(next === 'news' ? 'stories' : 'overview');
  }

  function handleLogout() {
    clearToken();
    navigate('/login');
  }

  // Intel (closed contour) — отдельный fullscreen-shell со своей витриной.
  if (mode === 'intel') {
    return <IntelApp onExit={() => handleModeChange('brand')} />;
  }

  return (
    <div className={styles.app}>
      <Sidebar
        mode={mode}
        screen={screen}
        setScreen={setScreen}
        onModeChange={handleModeChange}
        onLogout={handleLogout}
      />
      {mode === 'news'
        ? <NewsApp screen={screen} setScreen={setScreen} />
        : <BrandApp screen={screen} setScreen={setScreen} />}
    </div>
  );
}
