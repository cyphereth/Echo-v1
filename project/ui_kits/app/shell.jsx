// ============================================================================
// Echo Radar — App UI kit · shell (Sidebar + TopBar)
// ============================================================================

function NavItem({ icon, label, active, badge, onClick }) {
  return (
    <button onClick={onClick} className="er-nav" data-active={active ? '1' : '0'}>
      <Icon name={icon} size={18} />
      <span style={{ flex: 1, textAlign: 'left' }}>{label}</span>
      {badge != null && <span className="er-nav-badge">{badge}</span>}
    </button>
  );
}

function Sidebar({ screen, setScreen, prCount }) {
  return (
    <aside className="er-sidebar">
      <div style={{ padding: '20px 18px 16px' }}>
        <EchoWordmark size={22} />
      </div>
      <nav style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 12px' }}>
        <NavItem icon="inbox"    label="Инбокс"     active={screen === 'inbox'}  badge={prCount} onClick={() => setScreen('inbox')} />
        <NavItem icon="radio"    label="Зонды"      active={screen === 'probes'} onClick={() => setScreen('probes')} />
        <NavItem icon="building" label="Бренд"      active={false} onClick={() => setScreen('inbox')} />
        <NavItem icon="settings" label="Настройки"  active={false} onClick={() => setScreen('inbox')} />
      </nav>

      <div style={{ marginTop: 'auto', padding: 12 }}>
        <div className="er-status">
          <span className="er-pulse" />
          <div style={{ lineHeight: 1.3 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--sev-calm)', fontWeight: 600 }}>Эфир</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-3)' }}>4 зонда на связи</div>
          </div>
        </div>
        <div className="er-account">
          <Avatar name="Дарья" size={30} />
          <div style={{ lineHeight: 1.25, flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-1)' }}>Дарья · PR</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-3)' }}>{BRAND.name}</div>
          </div>
        </div>
      </div>
    </aside>
  );
}

function TopBar({ title, sub }) {
  return (
    <header className="er-topbar">
      <button className="er-brandsel">
        <span className="er-monogram">{BRAND.monogram}</span>
        <span style={{ lineHeight: 1.2, textAlign: 'left' }}>
          <span style={{ display: 'block', fontSize: 14, fontWeight: 700, color: 'var(--fg-1)' }}>{BRAND.name}</span>
          <span style={{ display: 'block', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-3)' }}>{BRAND.handle}</span>
        </span>
        <Icon name="chevronDown" size={15} color="var(--fg-3)" style={{ marginLeft: 2 }} />
      </button>

      <div className="er-topgrow">
        <div style={{ lineHeight: 1.2 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--fg-1)' }}>{title}</div>
          {sub && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-3)' }}>{sub}</div>}
        </div>
      </div>

      <div className="er-search">
        <Icon name="search" size={15} color="var(--fg-3)" />
        <span style={{ color: 'var(--fg-3)', fontSize: 13 }}>Поиск по упоминаниям…</span>
      </div>
      <button className="er-icbtn"><Icon name="bell" size={17} color="var(--fg-2)" /><span className="er-bell-dot" /></button>
    </header>
  );
}
