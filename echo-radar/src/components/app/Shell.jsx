import { Icon } from '../shared/icons';
import { EchoWordmark } from '../shared/EchoWordmark';
import { Avatar } from '../shared/primitives';
import { BRAND } from '../../data/mentions';
import styles from './app.module.css';

function NavItem({ icon, label, active, badge, onClick }) {
  return (
    <button onClick={onClick} className={styles.nav} data-active={active ? '1' : '0'}>
      <Icon name={icon} size={18} />
      <span style={{ flex: 1, textAlign: 'left' }}>{label}</span>
      {badge != null && <span className={styles.navBadge}>{badge}</span>}
    </button>
  );
}

export function Sidebar({ screen, setScreen, prCount }) {
  return (
    <aside className={styles.sidebar}>
      <div style={{ padding: '20px 18px 16px' }}>
        <EchoWordmark size={22} />
      </div>
      <nav style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 12px' }}>
        <NavItem icon="inbox"    label="Инбокс"    active={screen === 'inbox'}  badge={prCount} onClick={() => setScreen('inbox')} />
        <NavItem icon="radio"    label="Зонды"     active={screen === 'probes'} onClick={() => setScreen('probes')} />
        <NavItem icon="building" label="Бренд"     active={false} onClick={() => setScreen('inbox')} />
        <NavItem icon="settings" label="Настройки" active={false} onClick={() => setScreen('inbox')} />
      </nav>

      <div style={{ marginTop: 'auto', padding: 12 }}>
        <div className={styles.status}>
          <span className={styles.pulse} />
          <div style={{ lineHeight: 1.3 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--sev-calm)', fontWeight: 600 }}>Эфир</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-3)' }}>4 зонда на связи</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 6px' }}>
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

export function TopBar({ title, sub }) {
  return (
    <header className={styles.topbar}>
      <button className={styles.brandsel}>
        <span className={styles.monogram}>{BRAND.monogram}</span>
        <span style={{ lineHeight: 1.2, textAlign: 'left' }}>
          <span style={{ display: 'block', fontSize: 14, fontWeight: 700, color: 'var(--fg-1)' }}>{BRAND.name}</span>
          <span style={{ display: 'block', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-3)' }}>{BRAND.handle}</span>
        </span>
        <Icon name="chevronDown" size={15} color="var(--fg-3)" style={{ marginLeft: 2 }} />
      </button>

      <div style={{ flex: 1, whiteSpace: 'nowrap', minWidth: 0 }}>
        <div style={{ lineHeight: 1.2 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--fg-1)' }}>{title}</div>
          {sub && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-3)' }}>{sub}</div>}
        </div>
      </div>

      <div className={styles.search}>
        <Icon name="search" size={15} color="var(--fg-3)" />
        <span style={{ color: 'var(--fg-3)', fontSize: 13 }}>Поиск по упоминаниям…</span>
      </div>
      <button className={styles.icbtn} style={{ position: 'relative' }}>
        <Icon name="bell" size={17} color="var(--fg-2)" />
        <span className={styles.bellDot} />
      </button>
    </header>
  );
}
