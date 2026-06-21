// News workspace — isolated from brand. Manages topics, feed, and news screens.
// Rendered by AppPage when mode === 'news'.
import { useState, useEffect, useCallback } from 'react';
import { TopBar } from '../../components/app/Shell';
import { DetailPanel, EmptyDetail } from '../../components/app/Detail';
import { NewsStoriesScreen } from './components/Stories';
import { NewsDigestsScreen } from './components/Digests';
import { NewsSourcesScreen } from './components/Sources';
import { NewsFeed } from './components/Feed';
import * as newsApi from './api';
import styles from '../../components/app/shell.module.css';

// ── Topic pill bar ────────────────────────────────────────────────────────────

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

// ── Mention → feed item mapper ────────────────────────────────────────────────

function agoStr(isoString) {
  const mins = Math.round((Date.now() - new Date(isoString)) / 60000);
  if (mins < 1)    return 'только что';
  if (mins < 60)   return `${mins} мин`;
  if (mins < 1440) return `${Math.floor(mins / 60)} ч`;
  return `${Math.floor(mins / 1440)} д`;
}

function mentionToItem(m) {
  return {
    id:       m.id,
    platform: m.platform || 'telegram',
    author:   m.author,
    ago:      agoStr(m.created_at),
    title:    m.text.length > 80 ? m.text.slice(0, 80) + '…' : m.text,
    summary:  m.text,
    views:    m.views || 0,
    url:      m.url || null,
    _mentionId: m.id,
  };
}

// ── News workspace ────────────────────────────────────────────────────────────

const NEWS_SCREENS = ['stories', 'feed', 'digests', 'sources'];

// Props: screen, setScreen (controlled by AppPage Sidebar nav)
export function NewsApp({ screen, setScreen }) {
  const [topics, setTopics]           = useState([]);
  const [activeTopicId, setActiveTopicId] = useState(null);
  const [feedItems, setFeedItems]     = useState([]);
  const [selectedId, setSelectedId]   = useState(null);

  const activeTopic = topics.find((t) => t.id === activeTopicId) || null;

  // ── Load topics on mount ──
  const loadTopics = useCallback(async () => {
    try {
      const ts = await newsApi.getTopics();
      setTopics(ts);
      setActiveTopicId((prev) => prev ?? ts[0]?.id ?? null);
    } catch (e) {
      console.warn('Failed to load topics:', e.message);
    }
  }, []);

  useEffect(() => { loadTopics(); }, [loadTopics]);

  // ── Load news feed whenever active topic changes ──
  const loadFeed = useCallback(async (topicId) => {
    if (!topicId) { setFeedItems([]); return; }
    try {
      const inbox = await newsApi.getNewsFeed(topicId);
      // /news/inbox returns { pr: [], smm: [] } shape (mirrors legacy inbox)
      const all = [...(inbox.pr || []), ...(inbox.smm || [])];
      setFeedItems(all.map(mentionToItem));
    } catch (e) {
      console.warn('Failed to load news feed:', e.message);
    }
  }, []);

  useEffect(() => {
    setSelectedId(null);
    loadFeed(activeTopicId);
  }, [activeTopicId, loadFeed]);

  // ── Add topic ──
  async function handleAddTopic(name) {
    try {
      const t = await newsApi.createTopic(name, [name]);
      setTopics((prev) => [t, ...prev.filter((p) => p.id !== t.id)]);
      setActiveTopicId(t.id);
    } catch (e) {
      console.warn('Failed to add topic:', e.message);
    }
  }

  const selected = feedItems.find(i => i.id === selectedId) ?? null;

  return (
    <div className={styles.main}>
      <TopBar
        title={
          screen === 'feed'    ? 'Новости' :
          screen === 'stories' ? 'Сюжеты' :
          screen === 'digests' ? 'Дайджесты' :
          screen === 'sources' ? 'Источники' : 'Новости'
        }
        sub={
          screen === 'feed'
            ? (activeTopic?.name ? `Тема: ${activeTopic.name} · Telegram + веб` : 'Выберите тему')
            : undefined
        }
      />

      <TopicBar
        topics={topics}
        activeId={activeTopicId}
        onSelect={setActiveTopicId}
        onAdd={handleAddTopic}
      />

      {screen === 'feed' ? (
        <div className={styles.workspace}>
          <NewsFeed items={feedItems} selectedId={selectedId} onSelect={setSelectedId} />
          {selected ? <DetailPanel item={selected} /> : <EmptyDetail />}
        </div>
      ) : screen === 'stories' ? (
        <div className={styles.workspace}>
          <NewsStoriesScreen topicId={activeTopicId} />
        </div>
      ) : screen === 'digests' ? (
        <div className={styles.workspace}>
          <NewsDigestsScreen topicId={activeTopicId} />
        </div>
      ) : screen === 'sources' ? (
        <div className={styles.workspace}>
          <NewsSourcesScreen topicId={activeTopicId} />
        </div>
      ) : null}
    </div>
  );
}
