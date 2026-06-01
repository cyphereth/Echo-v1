import { useState } from 'react';
import { Sidebar, TopBar } from '../components/app/Shell';
import { Feed } from '../components/app/Feed';
import { DetailPanel, EmptyDetail } from '../components/app/Detail';
import { BRAND, FEED_ITEMS } from '../data/mock';
import styles from '../components/app/shell.module.css';

export default function AppPage() {
  const [screen, setScreen]     = useState('feed');
  const [selectedId, setSelectedId] = useState(null);

  const selected = FEED_ITEMS.find(i => i.id === selectedId) ?? null;

  return (
    <div className={styles.app}>
      <Sidebar screen={screen} setScreen={setScreen} brand={BRAND} />
      <div className={styles.main}>
        <TopBar
          title={screen === 'feed' ? 'Лента' : screen === 'queue' ? 'Очередь ответов' : screen === 'analytics' ? 'Аналитика' : 'Настройки'}
          sub={screen === 'feed' ? 'Instagram · TikTok · Telegram' : undefined}
        />
        {screen === 'feed' ? (
          <div className={styles.workspace}>
            <Feed selectedId={selectedId} onSelect={setSelectedId} />
            {selected ? <DetailPanel item={selected} /> : <EmptyDetail />}
          </div>
        ) : (
          <div style={{ flex: 1, display: 'grid', placeItems: 'center', color: 'var(--fg-4)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>
            {screen} — скоро
          </div>
        )}
      </div>
    </div>
  );
}
