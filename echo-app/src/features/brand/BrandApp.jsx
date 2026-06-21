// Brand workspace — isolated from news. Manages brand, feed, and brand screens.
// Mounted by Shell when mode === 'brand'.
import { useState, useEffect, useCallback, useRef } from 'react';
import { TopBar } from '../../components/app/Shell';
import { Button } from '../../core/components/ui';
import { BrandFeed } from './components/Feed';
import { DetailPanel, EmptyDetail } from './components/Detail';
import { QueueScreen } from './components/Queue';
import { AnalyticsScreen } from './components/Analytics';
import { SettingsScreen } from './components/Settings';
import { CityExplorerScreen } from './components/CityExplorer';
import { BrandDigestsScreen } from './components/Digests';
import { ProbesScreen } from './components/Probes';
import { OverviewScreen } from './components/Overview';
import { AIWizard } from './components/AIWizard';
import * as api from './api';
import styles from '../../components/app/shell.module.css';

// ── Mention → feed item mapper ────────────────────────────────────────────────

function agoStrLocal(isoString) {
  const mins = Math.round((Date.now() - new Date(isoString)) / 60000);
  if (mins < 1)    return 'только что';
  if (mins < 60)   return `${mins} мин`;
  if (mins < 1440) return `${Math.floor(mins / 60)} ч`;
  return `${Math.floor(mins / 1440)} д`;
}

function mentionToItem(m) {
  const lane = m.source || 'brand';
  // sparkline из snapshots (просмотры во времени) — иначе одиночная точка
  const viewsSeries = Array.isArray(m.snapshots) && m.snapshots.length
    ? m.snapshots.map(s => Number(s.views) || 0)
    : (m.views ? [m.views] : []);
  return {
    id:              m.id,
    lane,
    competitor:      m.competitor || null,
    opportunity:     m.opportunity || null,
    platform:        m.platform,
    author:          m.author,
    authorFollowers: m.followers,
    ago:             agoStrLocal(m.created_at),
    title:           m.text.length > 120 ? m.text.slice(0, 120) + '…' : m.text,
    summary:         m.text,
    views:           m.views,
    viewsSeries,
    likes:           m.likes || 0,
    severity:        Number(m.severity) || 0,
    phase:           m.phase || 'unknown',
    tone:            m.tone || 'neutral',
    confidence:      Number(m.confidence) || 0,
    category:        m.category || null,
    draft:           m.draft || null,
    draft_flag:      m.draft_flag || null,
    humor:           m.category === 'humor',
    commentsCount:   m.comments || 0,
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

// ── Brand workspace ───────────────────────────────────────────────────────────

// Props: screen, setScreen (controlled by Shell Sidebar nav)
export function BrandApp({ screen, setScreen }) {
  const [brand, setBrand]             = useState(null);
  const [brandLoaded, setBrandLoaded] = useState(false);
  const [feedItems, setFeedItems]     = useState([]);
  const [selectedId, setSelectedId]   = useState(null);
  const [collecting, setCollecting]   = useState(false);
  const [showWizard, setShowWizard]   = useState(false);
  const pollRef                       = useRef(null);

  const selected = feedItems.find(i => i.id === selectedId) ?? null;

  const loadFeed = useCallback(async (brandId) => {
    if (!brandId) { setFeedItems([]); return 0; }
    try {
      const inbox = await api.getBrandInbox(brandId);
      const all = [...inbox.pr, ...inbox.smm];
      setFeedItems(all.map(mentionToItem));
      return all.length;
    } catch { return 0; }
  }, []);

  const loadBrand = useCallback(async () => {
    try {
      const list = await api.getBrands();
      const b = Array.isArray(list) ? list[0] ?? null : null;
      setBrand(b);
      setBrandLoaded(true);
      if (b?.id) loadFeed(b.id);
    } catch {
      setBrandLoaded(true);
    }
  }, [loadFeed]);

  useEffect(() => { loadBrand(); }, [loadBrand]);
  useEffect(() => () => clearInterval(pollRef.current), []);

  // Reload feed when brand changes
  useEffect(() => {
    if (brand?.id) loadFeed(brand.id);
    else setFeedItems([]);
    setSelectedId(null);
  }, [brand?.id, loadFeed]);

  const handleCollect = useCallback(async () => {
    if (!brand || collecting) return;
    setCollecting(true);
    try {
      await api.collectBrand(brand.id);
    } catch {
      setCollecting(false);
      return;
    }
    let polls = 0;
    pollRef.current = setInterval(async () => {
      polls++;
      const n = await loadFeed(brand.id);
      if (n > 0 || polls >= 6) {
        clearInterval(pollRef.current);
        setCollecting(false);
      }
    }, 3000);
  }, [brand, collecting, loadFeed]);

  const handleBrandSaved = useCallback(async (updatedBrand) => {
    setBrand(updatedBrand);
    setScreen('feed');
    await loadFeed(updatedBrand.id);
  }, [loadFeed, setScreen]);

  // Brand with no brand yet → show onboarding wizard fullscreen
  if (brandLoaded && !brand) {
    return <AIWizard mode="create" onSaved={handleBrandSaved} />;
  }

  const topBarTitle =
    screen === 'overview'  ? 'Обзор' :
    screen === 'feed'      ? 'Лента' :
    screen === 'queue'     ? 'Очередь ответов' :
    screen === 'analytics' ? 'Аналитика' :
    screen === 'digests'   ? 'Дайджесты' :
    screen === 'probes'    ? 'Зонды' :
    screen === 'cities'    ? 'Города' : 'Настройки';

  const topBarSub = screen === 'feed'
    ? 'Instagram · TikTok · Telegram · реальные данные'
    : undefined;

  return (
    <div className={styles.main}>
      <TopBar title={topBarTitle} sub={topBarSub}>
        {brand && (
          <Button
            variant={collecting ? 'secondary' : 'primary'}
            size="sm"
            icon={collecting ? 'refresh' : 'zap'}
            onClick={handleCollect}
            disabled={collecting}
          >
            {collecting ? 'Сбор данных…' : 'Собрать данные'}
          </Button>
        )}
      </TopBar>

      {screen === 'overview' ? (
        <div className={styles.workspace}><OverviewScreen brand={brand} /></div>
      ) : screen === 'feed' ? (
        <div className={styles.splitView}>
          <BrandFeed items={feedItems} selectedId={selectedId} onSelect={setSelectedId} />
          {selected ? <DetailPanel item={selected} /> : <EmptyDetail />}
        </div>
      ) : screen === 'queue' ? (
        <div className={styles.workspace}><QueueScreen items={feedItems} brandId={brand?.id} /></div>
      ) : screen === 'analytics' ? (
        <div className={styles.workspace}><AnalyticsScreen brandId={brand?.id} /></div>
      ) : screen === 'digests' ? (
        <div className={styles.workspace}><BrandDigestsScreen brandId={brand?.id} /></div>
      ) : screen === 'probes' ? (
        <div className={styles.workspace}><ProbesScreen brand={brand} onBrandSaved={handleBrandSaved} /></div>
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
