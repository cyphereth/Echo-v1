// Intel closed contour — shell + экраны.
// Situational Center (home) / Stories / Sources / Antispam / Feed v2.
// Витринная тема «военный диспетчер»: темнее, координатная сетка, моно-данные.
import { useState, useEffect, useRef, useCallback } from 'react';
import { Icon } from '../../core/components/icons';
import { IntelHome } from './components/IntelHome';
import { IntelStories } from './components/IntelStories';
import { IntelFeed } from './components/IntelFeed';
import { IntelSources } from './components/IntelSources';
import { IntelSpam } from './components/IntelSpam';
import { AlertBell } from './components/AlertBell';
import { AlertToast } from './components/AlertToast';
import { DateRangePicker } from './components/DateRangePicker';
import { intelApi, streamLiveEvents } from './api';
import { INTEL_USE_MOCK } from './data/mock';
import styles from './intel.module.css';

const SCREENS = [
  { key: 'home',    label: 'Ситуационный центр', icon: 'radio',    hotkey: '1' },
  { key: 'stories', label: 'Сюжеты',             icon: 'activity', hotkey: '2' },
  { key: 'sources', label: 'Источники',           icon: 'link',     hotkey: '3' },
  { key: 'spam',    label: 'Антиспам',             icon: 'search',   hotkey: '4' },
  { key: 'feed',    label: 'Лента событий v2',   icon: 'radio',    hotkey: '5' },
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
  const [screen, setScreen]       = useState('home');
  const [timeRange, setTimeRange] = useState({ window: '24h' });
  const [openStoryId, setOpenStoryId] = useState(null);
  const [openDirection, setOpenDirection] = useState(null);
  const [navToken, setNavToken] = useState(0);
  const [search, setSearch]   = useState('');
  const [searchResults, setSearchResults] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const [alerts, setAlerts]         = useState([]);
  const [muted, setMuted] = useState({ stories: [], directions: [] });
  const [toasts, setToasts]         = useState([]);
  const seenAlert = useRef(new Set());
  // Feed state that must SURVIVE switching tabs (IntelHome unmounts on tab change,
  // so keeping these here is what stops hidden/seen posts from resurrecting as «new»
  // out of the persistent liveEvents buffer when you come back to the home screen).
  const [hiddenIds, setHiddenIds] = useState(() => new Set());
  const seenIdsRef = useRef(new Set());

  // Hide a feed event: remember it AND drop it from the live buffer so a later
  // IntelHome remount can't re-merge it back in.
  const hideEvent = useCallback((id) => {
    setHiddenIds(prev => { const n = new Set(prev); n.add(id); return n; });
    setLiveEvents(prev => prev.filter(e => e.id !== id));
  }, []);

  useEffect(() => {
    let alive = true;
    intelApi.alerts({ unread: true, limit: 50 }).then(rows => {
      if (!alive || !Array.isArray(rows)) return;
      rows.forEach(a => seenAlert.current.add(a.id));
      setAlerts(rows);
    }).catch(() => {});
    intelApi.mutedList().then(setMuted).catch(() => {});

    const stop = streamLiveEvents({
      // -1 → сервер стартует с max(alert.id): шлёт ТОЛЬКО новые сигналы, появившиеся
      // после подключения. Иначе при перезаходе все старые алерты летят тостами.
      afterAlertId: -1,
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

  const muteFromAlert = useCallback(async (a) => {
    // оптимистично убираем все сигналы того же объекта из ленты
    setAlerts(prev => prev.filter(x => a.scope === 'direction'
      ? x.direction_id !== a.direction_id
      : x.story_id !== a.story_id));
    try {
      if (a.scope === 'direction') await intelApi.muteDirection(a.direction_id);
      else await intelApi.muteStory(a.story_id);
      setMuted(await intelApi.mutedList());
    } catch { /* optimistic */ }
  }, []);

  const unmute = useCallback(async (kind, id) => {
    setMuted(prev => ({
      stories: kind === 'story' ? prev.stories.filter(s => s.id !== id) : prev.stories,
      directions: kind === 'direction' ? prev.directions.filter(d => d.id !== id) : prev.directions,
    }));
    try {
      if (kind === 'direction') await intelApi.unmuteDirection(id);
      else await intelApi.unmuteStory(id);
    } catch { /* optimistic */ }
  }, []);

  const TWO_HOURS_MS = 2 * 60 * 60 * 1000;
  const visibleAlerts = alerts.filter(a => a.at && (Date.now() - new Date(a.at).getTime()) < TWO_HOURS_MS);
  const unreadCount = visibleAlerts.filter(a => !a.acknowledged).length;

  async function runSearch(q) {
    if (!q.trim()) { setSearchResults(null); return; }
    setSearchResults(await intelApi.search(q.trim()));
  }

  // Открыть сигнал: ведём к КОНКРЕТНОМУ сюжету (scope=story) или направлению,
  // а не просто на вкладку «Сюжеты». navToken гарантирует переход даже если экран
  // уже открыт. Раньше onOpen только переключал screen — клик «не туда».
  const openAlert = (a) => {
    if (a.scope === 'story' && a.story_id != null) {
      setOpenStoryId(a.story_id); setOpenDirection(null);
    } else if (a.direction) {
      setOpenDirection(a.direction); setOpenStoryId(null);
    } else {
      setScreen('stories');
      return;
    }
    setNavToken(t => t + 1);
    setScreen('stories');
  };

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
            <NavItem key={s.key} item={s} active={screen === s.key} onClick={() => { setScreen(s.key); setSearchResults(null); setOpenStoryId(null); setOpenDirection(null); }} />
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
          <AlertBell alerts={visibleAlerts} unreadCount={unreadCount} onAck={ackAlert} onAckAll={ackAll}
                     onOpen={openAlert} onMute={muteFromAlert} muted={muted} onUnmute={unmute} />
          <DateRangePicker value={timeRange} onChange={setTimeRange} />
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
          <IntelHome timeRange={timeRange} liveEvents={liveEvents}
                     hiddenIds={hiddenIds} hideEvent={hideEvent} seenIdsRef={seenIdsRef}
                     onOpenStory={(id) => { setOpenStoryId(id ?? null); setOpenDirection(null); setNavToken(t => t + 1); setScreen('stories'); }} />
        ) : screen === 'stories' ? (
          <IntelStories timeRange={timeRange} openStoryId={openStoryId} openDirection={openDirection} navToken={navToken} />
        ) : screen === 'sources' ? (
          <IntelSources />
        ) : screen === 'feed' ? (
          <IntelFeed />
        ) : (
          <IntelSpam />
        )}
        <AlertToast toasts={toasts} onDismiss={dismissToast}
                    onOpen={(a) => { openAlert(a); dismissToast(a.id); }} />
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
