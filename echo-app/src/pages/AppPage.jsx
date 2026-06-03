import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sidebar, TopBar } from '../components/app/Shell';
import { Feed } from '../components/app/Feed';
import { DetailPanel, EmptyDetail } from '../components/app/Detail';
import { QueueScreen } from '../components/app/Queue';
import { AnalyticsScreen } from '../components/app/Analytics';
import { SettingsScreen } from '../components/app/Settings';
import * as api from '../services/api';
import styles from '../components/app/shell.module.css';

function agoStr(isoString) {
  const mins = Math.round((Date.now() - new Date(isoString)) / 60000);
  if (mins < 1)    return 'только что';
  if (mins < 60)   return `${mins} мин`;
  if (mins < 1440) return `${Math.floor(mins / 60)} ч`;
  return `${Math.floor(mins / 1440)} д`;
}

function mentionToItem(m) {
  const lane = m.source || 'brand';
  const thumbnail =
    lane === 'competitor' ? 'competitor' :
    lane === 'niche'      ? 'niche' :
    m.tone === 'negative' ? 'neg' : 'neutral';
  return {
    id:              m.id,
    lane,
    competitor:      m.competitor || null,
    opportunity:     m.opportunity || null,
    platform:        m.platform,
    author:          m.author,
    authorFollowers: m.followers,
    ago:             agoStr(m.created_at),
    title:           m.text.length > 80 ? m.text.slice(0, 80) + '…' : m.text,
    summary:         m.text,
    views:           m.views,
    likes:           m.likes || 0,
    severity:        m.severity || 0,
    negativeCommentPct: m.tone === 'negative' ? 72 : 15,
    commentsCount:   m.comments || 0,
    thumbnail,
    url:             m.url || null,
    comments:        m.draft ? [{
      id:            `c_${m.id}`,
      author:        m.author,
      followers:     m.followers,
      text:          m.text,
      sentiment:     m.tone || 'neutral',
      pendingReply:  null,
      suggestedReply: m.draft,
      status:        m.status === 'sent' ? 'approved' : 'pending',
      likes:         m.likes || 0,
      minsAgo:       Math.round((Date.now() - new Date(m.created_at)) / 60000),
    }] : [],
    _mentionId: m.id,
    status:     m.status,
  };
}

export default function AppPage() {
  const navigate = useNavigate();
  const [screen, setScreen]         = useState('feed');
  const [selectedId, setSelectedId] = useState(null);
  const [brand, setBrand]           = useState(null);
  const [brands, setBrands]         = useState([]);
  const [feedItems, setFeedItems]   = useState([]);
  const [usingReal, setUsingReal]   = useState(false);
  const [collecting, setCollecting] = useState(false);
  const pollRef                     = useRef(null);

  const loadFeed = useCallback(async (brandId) => {
    try {
      const inbox = await api.getInbox(brandId);
      const all = [...inbox.pr, ...inbox.smm];
      if (all.length > 0) {
        setFeedItems(all.map(mentionToItem));
        setUsingReal(true);
      }
    } catch (e) {
      console.warn('Failed to load inbox:', e.message);
    }
  }, []);

  const loadBrand = useCallback(async () => {
    try {
      const list = await api.getBrands();
      setBrands(list);
      if (list.length > 0) {
        setBrand(prev => list.find(b => b.id === prev?.id) ?? list[0]);
        loadFeed((list.find(b => b.id === brand?.id) ?? list[0]).id);
      }
    } catch (e) {
      console.warn('Backend unavailable, using demo data');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadFeed]);

  useEffect(() => { loadBrand(); }, [loadBrand]);

  function selectBrand(id) {
    const b = brands.find(x => x.id === id);
    if (!b) return;
    setBrand(b);
    setSelectedId(null);
    setUsingReal(false);
    loadFeed(b.id);
    setScreen('feed');
  }

  function newBrand() {
    setBrand(null);
    setScreen('settings');
  }

  function handleLogout() {
    api.logout();
    navigate('/login', { replace: true });
  }

  useEffect(() => () => clearInterval(pollRef.current), []);

  async function handleCollect() {
    if (!brand || collecting) return;
    setCollecting(true);
    try {
      await api.collectBrand(brand.id);
    } catch (e) {
      setCollecting(false);
      return;
    }

    let ticks = 0;
    pollRef.current = setInterval(async () => {
      ticks++;
      await loadFeed(brand.id);
      if (ticks >= 6) {
        clearInterval(pollRef.current);
        setCollecting(false);
      }
    }, 3000);
  }

  async function handleBrandSaved(updatedBrand) {
    setBrand(updatedBrand);
    if (updatedBrand?.id) {
      setBrands(prev => prev.some(b => b.id === updatedBrand.id)
        ? prev.map(b => b.id === updatedBrand.id ? updatedBrand : b)
        : [...prev, updatedBrand]);
      await loadFeed(updatedBrand.id);
    }
  }

  const selected = feedItems.find(i => i.id === selectedId) ?? null;

  return (
    <div className={styles.app}>
      <Sidebar
        screen={screen}
        setScreen={setScreen}
        brand={brand ?? { name: 'PapaPizza', niche: 'доставка еды' }}
        brands={brands}
        activeBrandId={brand?.id}
        onSelectBrand={selectBrand}
        onNewBrand={newBrand}
        onLogout={handleLogout}
      />
      <div className={styles.main}>
        <TopBar
          title={
            screen === 'feed'      ? 'Лента' :
            screen === 'queue'     ? 'Очередь ответов' :
            screen === 'analytics' ? 'Аналитика' : 'Настройки'
          }
          sub={screen === 'feed'
            ? `Instagram · TikTok · Telegram${usingReal ? ' · реальные данные' : ' · демо'}`
            : undefined}
        >
          {brand && (
            <button
              onClick={handleCollect}
              disabled={collecting}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '7px 16px', borderRadius: 'var(--r-md)',
                background: collecting ? 'var(--surface-3)' : 'var(--brand)',
                color: collecting ? 'var(--fg-3)' : '#fff',
                border: 'none', cursor: collecting ? 'default' : 'pointer',
                fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-sans)',
                transition: 'all 0.15s', whiteSpace: 'nowrap',
              }}
            >
              {collecting ? '⏳ Сбор данных…' : '⚡ Собрать данные'}
            </button>
          )}
        </TopBar>

        {screen === 'feed' ? (
          <div className={styles.workspace}>
            <Feed items={feedItems} selectedId={selectedId} onSelect={setSelectedId} />
            {selected ? <DetailPanel item={selected} /> : <EmptyDetail />}
          </div>
        ) : screen === 'queue' ? (
          <div className={styles.workspace}><QueueScreen items={feedItems} /></div>
        ) : screen === 'analytics' ? (
          <div className={styles.workspace}><AnalyticsScreen brandId={brand?.id} /></div>
        ) : (
          <div className={styles.workspace}>
            <SettingsScreen
              brand={brand}
              onBrandSaved={handleBrandSaved}
              onCollect={handleCollect}
              collecting={collecting}
            />
          </div>
        )}
      </div>
    </div>
  );
}
