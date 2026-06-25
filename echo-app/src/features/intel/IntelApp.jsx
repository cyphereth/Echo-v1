// Intel closed contour — shell + 3 экрана.
// Situational Center (home) / Stories / Operational Board.
// Витринная тема «военный диспетчер»: темнее, координатная сетка, моно-данные.
import { useState, useEffect, useRef, useCallback } from 'react';
import { Icon } from '../../core/components/icons';
import { IntelHome } from './components/IntelHome';
import { IntelStories } from './components/IntelStories';
import { IntelBoard } from './components/IntelBoard';
import { IntelSources } from './components/IntelSources';
import { AlertBell } from './components/AlertBell';
import { AlertToast } from './components/AlertToast';
import { intelApi, streamLiveEvents } from './api';
import { INTEL_USE_MOCK } from './data/mock';
import styles from './intel.module.css';

const SCREENS = [
  { key: 'home',    label: 'Ситуационный центр', icon: 'radio',    hotkey: '1' },
  { key: 'stories', label: 'Сюжеты',             icon: 'activity', hotkey: '2' },
  { key: 'board',   label: 'Оперативная доска',  icon: 'bar3',     hotkey: '3' },
  { key: 'sources', label: 'Источники',           icon: 'link',     hotkey: '4' },
];

function NavItem({ item, active, onClick }) {
  return (
    <button className={styles.navItem} data-active={active ? '1' : '0'} onClick={onClick}>
      <Icon name={item.icon} size={15} />
      <span style={{ flex: 1 }}>{item.label}</span>
      <span className={styles.navKey}>{item.hotkey}</span>
    </button>
  );
}

export function IntelApp({ onExit }) {
  const [screen, setScreen]   = useState('home');
  const [window, setWindow]   = useState('24h');
  const [search, setSearch]   = useState('');
  const [searchResults, setSearchResults] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const [alerts, setAlerts]         = useState([]);
  const [toasts, setToasts]         = useState([]);
  const seenAlert = useRef(new Set());

  useEffect(() => {
    let alive = true;
    intelApi.alerts({ unread: true, limit: 50 }).then(rows => {
      if (!alive || !Array.isArray(rows)) return;
      rows.forEach(a => seenAlert.current.add(a.id));
      setAlerts(rows);
    }).catch(() => {});

    const stop = streamLiveEvents({
      onEvent: (e) => {
        if (!alive || !e || e.id == null) return;
        setLiveEvents(prev => [...prev, e].slice(-200));
      },
      onAlert: (a) => {
        if (!alive || !a || a.id == null || seenAlert.current.has(a.id)) return;
        seenAlert.current.add(a.id);
        setAlerts(prev => [a, ...prev]);
        setToasts(prev => [...prev, a]);
      },
    });
    return () => { alive = false; stop(); };
  }, []);

  const dismissToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const ackAlert = useCallback(async (id) => {
    setAlerts(prev => prev.map(a => a.id === id ? { ...a, acknowledged: true } : a));
    try { await intelApi.ackAlert(id); } catch { /* optimistic */ }
  }, []);

  const ackAll = useCallback(async () => {
    setAlerts(prev => prev.map(a => ({ ...a, acknowledged: true })));
    try { await intelApi.ackAllAlerts(); } catch { /* optimistic */ }
  }, []);

  const unreadCount = alerts.filter(a => !a.acknowledged).length;

  async function runSearch(q) {
    if (!q.trim()) { setSearchResults(null); return; }
    setSearchResults(await intelApi.search(q.trim()));
  }

  return (
    <div className={styles.app}>
      {/* sidebar */}
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <div className={styles.brandName}>Echo · Разведка</div>
          <div className={styles.brandSub}>Closed contour</div>
          <span className={styles.classified}>⚠ ДСП · Закрытый</span>
        </div>
        <nav className={styles.nav}>
          {SCREENS.map(s => (
            <NavItem key={s.key} item={s} active={screen === s.key} onClick={() => { setScreen(s.key); setSearchResults(null); }} />
          ))}
        </nav>
        <div className={styles.sidebarBottom}>
          <div className={styles.statusRow}>
            <span className={styles.statusDot} />
            {INTEL_USE_MOCK ? 'В эфире · mock-данные' : 'В эфире · live'}
          </div>
          {onExit && (
            <button onClick={onExit} className={styles.navItem} style={{ width: '100%', marginTop: 8, justifyContent: 'center' }}>
              <Icon name="arrowLeft" size={13} />
              <span>К коммерческому контуру</span>
            </button>
          )}
        </div>
      </aside>

      {/* main */}
      <div className={styles.main}>
        <header className={styles.topbar}>
          <div>
            <div className={styles.topbarTitle}>
              {SCREENS.find(s => s.key === screen)?.label}
            </div>
          </div>
          <div className={styles.topgrow} />
          <AlertBell alerts={alerts} unreadCount={unreadCount} onAck={ackAlert} onAckAll={ackAll}
                     onOpen={(a) => setScreen(a.scope === 'story' ? 'stories' : 'board')} />
          <div className={styles.windowSel}>
            {['1h', '24h', '7d'].map(w => (
              <button key={w} className={styles.windowBtn} data-active={window === w ? '1' : '0'} onClick={() => setWindow(w)}>
                {w}
              </button>
            ))}
          </div>
          <div className={styles.searchBox}>
            <Icon name="search" size={13} color="#4A6378" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && runSearch(search)}
              placeholder="поиск по сюжетам…"
            />
          </div>
        </header>

        {searchResults ? (
          <div className={styles.workspace}>
            <SearchResults results={searchResults} query={search} onOpenStory={() => { setScreen('stories'); setSearchResults(null); }} />
          </div>
        ) : screen === 'home' ? (
          <IntelHome window={window} liveEvents={liveEvents} onOpenStory={() => setScreen('stories')} />
        ) : screen === 'stories' ? (
          <IntelStories window={window} />
        ) : screen === 'board' ? (
          <IntelBoard window={window} onOpenDir={() => setScreen('stories')} />
        ) : (
          <IntelSources />
        )}
        <AlertToast toasts={toasts} onDismiss={dismissToast}
                    onOpen={(a) => { setScreen(a.scope === 'story' ? 'stories' : 'board'); dismissToast(a.id); }} />
      </div>
    </div>
  );
}

function SearchResults({ results, query, onOpenStory }) {
  return (
    <>
      <div className={styles.section}>
        <div className={styles.sectionHead}>
          <span className={styles.sectionTitle}>
            <Icon name="search" size={13} color="#57D2E2" />
            Результаты поиска
            <span className={styles.sectionCount}>{results.length}</span>
          </span>
          <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 11, color: '#6A8499' }}>
            «{query}»
          </span>
        </div>
        {results.length === 0 ? (
          <div className={styles.empty}>Ничего не найдено.</div>
        ) : (
          results.map(r => (
            <div key={r.id} className={styles.hotRow} onClick={onOpenStory}>
              <span className={styles.hotTitle}>{r.title}</span>
              <span className={styles.hotDir}>{r.direction}</span>
            </div>
          ))
        )}
      </div>
    </>
  );
}
