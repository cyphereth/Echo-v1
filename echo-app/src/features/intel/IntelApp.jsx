// Intel closed contour — shell + 3 экрана.
// Situational Center (home) / Stories / Operational Board.
// Витринная тема «военный диспетчер»: темнее, координатная сетка, моно-данные.
import { useState } from 'react';
import { Icon } from '../../core/components/icons';
import { IntelHome } from './components/IntelHome';
import { IntelStories } from './components/IntelStories';
import { IntelBoard } from './components/IntelBoard';
import { intelApi } from './api';
import { INTEL_USE_MOCK } from './data/mock';
import styles from './intel.module.css';

const SCREENS = [
  { key: 'home',    label: 'Ситуационный центр', icon: 'radio',    hotkey: '1' },
  { key: 'stories', label: 'Сюжеты',             icon: 'activity', hotkey: '2' },
  { key: 'board',   label: 'Оперативная доска',  icon: 'bar3',     hotkey: '3' },
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
          <IntelHome window={window} onOpenStory={() => setScreen('stories')} />
        ) : screen === 'stories' ? (
          <IntelStories window={window} />
        ) : (
          <IntelBoard window={window} onOpenDir={() => setScreen('stories')} />
        )}
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
