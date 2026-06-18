import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sidebar, TopBar } from '../components/app/Shell';
import { Feed } from '../components/app/Feed';
import { DetailPanel, EmptyDetail } from '../components/app/Detail';
import { QueueScreen } from '../components/app/Queue';
import { AnalyticsScreen } from '../components/app/Analytics';
import { SettingsScreen } from '../components/app/Settings';
import { CityExplorerScreen } from '../components/app/CityExplorer';
import { StoriesScreen } from '../components/app/Stories';
import { DigestsScreen } from '../components/app/Digests';
import { AIWizard } from '../components/app/AIWizard';
import * as api from '../services/api';
import styles from '../components/app/shell.module.css';

const NEWS_SCREENS = ['feed', 'stories', 'digests'];

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

function TopicBar({ topics, activeId, onSelect, onAdd }) {
  const [val, setVal] = useState('');
  const pill = (active) => ({
    padding: '6px 14px', borderRadius: 999, border: 'none', cursor: 'pointer',
    fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-sans)',
    background: active ? 'var(--brand)' : 'var(--surface-3)',
    color: active ? '#fff' : 'var(--fg-2)', transition: 'all 0.15s', whiteSpace: 'nowrap',
  });
  return (
    <div style={{
      display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
      padding: '12px 20px', borderBottom: '1px solid var(--border)',
    }}>
      {topics.map((t) => (
        <button key={t.id} style={pill(t.id === activeId)} onClick={() => onSelect(t.id)}>
          {t.kind === 'default' ? t.name : `# ${t.name}`}
        </button>
      ))}
      <form
        onSubmit={(e) => { e.preventDefault(); const v = val.trim(); if (v) { onAdd(v); setVal(''); } }}
        style={{ display: 'flex' }}
      >
        <input
          value={val}
          onChange={(e) => setVal(e.target.value)}
          placeholder="+ своя тема…"
          style={{
            padding: '6px 12px', borderRadius: 999, border: '1px solid var(--border)',
            background: 'var(--surface-2)', color: 'var(--fg-1)', fontSize: 13,
            fontFamily: 'var(--font-sans)', outline: 'none', width: 150,
          }}
        />
      </form>
    </div>
  );
}

export default function AppPage() {
  const navigate = useNavigate();
  const [mode, setMode]               = useState('news');   // 'news' | 'brand'
  const [screen, setScreen]           = useState('feed');
  const [selectedId, setSelectedId]   = useState(null);
  const [brand, setBrand]             = useState(null);
  const [brandLoaded, setBrandLoaded] = useState(false);
  const [topics, setTopics]           = useState([]);
  const [activeTopicId, setActiveTopicId] = useState(null);
  const [feedItems, setFeedItems]     = useState([]);
  const [collecting, setCollecting]   = useState(false);
  const [showWizard, setShowWizard]   = useState(false);
  const pollRef                       = useRef(null);

  // Current scope: a topic in news mode, the brand in brand mode (null until ready).
  const activeTopic = topics.find((t) => t.id === activeTopicId) || null;
  const scope = mode === 'news'
    ? (activeTopicId ? { kind: 'topic', id: activeTopicId, name: activeTopic?.name } : null)
    : (brand?.id ? { kind: 'brand', id: brand.id, name: brand.name } : null);

  const loadFeed = useCallback(async (sc) => {
    if (!sc?.id) { setFeedItems([]); return 0; }
    try {
      const inbox = await api.getInboxScoped(sc);
      const all = [...inbox.pr, ...inbox.smm];
      setFeedItems(all.map(mentionToItem));
      return all.length;
    } catch (e) {
      console.warn('Failed to load inbox:', e.message);
      return 0;
    }
  }, []);

  const loadBrand = useCallback(async () => {
    try {
      const list = await api.getBrands();
      if (list.length > 0) setBrand(list[0]);
    } catch (e) {
      console.warn('Backend unavailable');
    }
    setBrandLoaded(true);
  }, []);

  const loadTopics = useCallback(async () => {
    try {
      const ts = await api.getNewsTopics();
      setTopics(ts);
      setActiveTopicId((prev) => prev ?? ts[0]?.id ?? null);
    } catch (e) {
      console.warn('Failed to load topics:', e.message);
    }
  }, []);

  useEffect(() => { loadBrand(); loadTopics(); }, [loadBrand, loadTopics]);
  useEffect(() => () => clearInterval(pollRef.current), []);

  // Reload feed whenever the active scope changes.
  useEffect(() => {
    if (mode === 'news' && activeTopicId) loadFeed({ kind: 'topic', id: activeTopicId });
    else if (mode === 'brand' && brand?.id) loadFeed({ kind: 'brand', id: brand.id });
    else setFeedItems([]);
    setSelectedId(null);
  }, [mode, activeTopicId, brand?.id, loadFeed]);

  function handleModeChange(m) {
    setScreen((s) => (m === 'news' && !NEWS_SCREENS.includes(s)) ? 'feed' : s);
    setMode(m);
  }

  async function handleAddTopic(name) {
    try {
      const t = await api.createNewsTopic(name, [name]);
      setTopics((prev) => [t, ...prev.filter((p) => p.id !== t.id)]);
      setActiveTopicId(t.id);
    } catch (e) {
      console.warn('Failed to add topic:', e.message);
    }
  }

  function handleLogout() {
    api.logout();
    navigate('/login', { replace: true });
  }

  async function handleCollect() {
    if (!brand || collecting) return;
    setCollecting(true);
    try { await api.collectBrand(brand.id); } catch { setCollecting(false); return; }
    let ticks = 0;
    pollRef.current = setInterval(async () => {
      ticks++;
      const n = await loadFeed({ kind: 'brand', id: brand.id });
      if (n > 0 || ticks >= 12) { clearInterval(pollRef.current); setCollecting(false); }
    }, 4000);
  }

  async function handleBrandSaved(updatedBrand) {
    setBrand(updatedBrand);
    setShowWizard(false);
    setMode('brand');
    if (!updatedBrand?.id) return;
    await loadFeed({ kind: 'brand', id: updatedBrand.id });
    // The wizard kicks off a background collect; the first run scans all probes
    // and takes a while, so poll the feed until results land (up to ~80s).
    setCollecting(true);
    clearInterval(pollRef.current);
    let ticks = 0;
    pollRef.current = setInterval(async () => {
      ticks++;
      const n = await loadFeed({ kind: 'brand', id: updatedBrand.id });
      if (n > 0 || ticks >= 20) { clearInterval(pollRef.current); setCollecting(false); }
    }, 4000);
  }

  // Brand mode with no brand yet → show onboarding wizard fullscreen.
  if (mode === 'brand' && brandLoaded && !brand) {
    return <AIWizard mode="create" onSaved={handleBrandSaved} />;
  }

  const selected = feedItems.find(i => i.id === selectedId) ?? null;

  return (
    <div className={styles.app}>
      <Sidebar
        screen={screen}
        setScreen={setScreen}
        brand={brand}
        onLogout={handleLogout}
        mode={mode}
        onModeChange={handleModeChange}
      />
      <div className={styles.main}>
        <TopBar
          title={
            screen === 'feed'      ? (mode === 'news' ? 'Новости' : 'Лента') :
            screen === 'queue'     ? 'Очередь ответов' :
            screen === 'analytics' ? 'Аналитика' :
            screen === 'stories'   ? 'Сюжеты' :
            screen === 'digests'   ? 'Дайджесты' :
            screen === 'cities'    ? 'Города' : 'Настройки'
          }
          sub={
            screen === 'feed'
              ? (mode === 'news'
                  ? (scope?.name ? `Тема: ${scope.name} · Telegram + веб` : 'Выберите тему')
                  : 'Instagram · TikTok · Telegram · реальные данные')
              : undefined
          }
        >
          {mode === 'brand' && brand && (
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

        {mode === 'news' && (
          <TopicBar
            topics={topics}
            activeId={activeTopicId}
            onSelect={setActiveTopicId}
            onAdd={handleAddTopic}
          />
        )}

        {screen === 'feed' ? (
          <div className={styles.workspace}>
            <Feed items={feedItems} selectedId={selectedId} onSelect={setSelectedId} />
            {selected ? <DetailPanel item={selected} /> : <EmptyDetail />}
          </div>
        ) : screen === 'queue' ? (
          <div className={styles.workspace}><QueueScreen items={feedItems} brandId={brand?.id} /></div>
        ) : screen === 'analytics' ? (
          <div className={styles.workspace}><AnalyticsScreen brandId={brand?.id} /></div>
        ) : screen === 'stories' ? (
          <div className={styles.workspace}><StoriesScreen scope={scope} /></div>
        ) : screen === 'digests' ? (
          <div className={styles.workspace}><DigestsScreen scope={scope} /></div>
        ) : screen === 'cities' ? (
          <div className={styles.workspace}><CityExplorerScreen /></div>
        ) : (
          <div className={styles.workspace}>
            <SettingsScreen
              brand={brand}
              onBrandSaved={handleBrandSaved}
              onCollect={handleCollect}
              collecting={collecting}
              onOpenWizard={() => setShowWizard(true)}
            />
          </div>
        )}
      </div>

      {showWizard && (
        <AIWizard
          mode="edit"
          brand={brand}
          onSaved={handleBrandSaved}
          onClose={() => setShowWizard(false)}
        />
      )}
    </div>
  );
}
