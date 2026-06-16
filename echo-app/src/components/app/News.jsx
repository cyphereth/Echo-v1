import { useEffect, useMemo, useState } from 'react';
import * as api from '../../services/api';
import styles from './news.module.css';

const SPEEDS = ['1x', '4x', '16x', '40x'];

const FALLBACK_TOPICS = [
  { id: null, name: 'Военные действия' },
  { id: null, name: 'Геополитика' },
  { id: null, name: 'Экономика' },
  { id: null, name: 'Энергетика' },
];

const FALLBACK_EVENTS = [
  { id: 1, time: '03:18', type: 'БПЛА', zone: 'Юг', sources: 18, confidence: 91, tone: 'high', text: 'Рост сообщений о движении БПЛА из нескольких Telegram-каналов и локальных чатов.' },
  { id: 2, time: '03:42', type: 'ПВО', zone: 'Центр', sources: 12, confidence: 84, tone: 'medium', text: 'Синхронные сообщения о работе ПВО, подтверждение из независимых источников задерживается.' },
  { id: 3, time: '04:06', type: 'Взрывы', zone: 'Восток', sources: 9, confidence: 77, tone: 'high', text: 'Несколько каналов фиксируют взрывы, часть сообщений требует проверки географии.' },
  { id: 4, time: '04:27', type: 'Радар', zone: 'Север', sources: 7, confidence: 69, tone: 'low', text: 'Появился слабый сигнал по новым каналам, пока без устойчивого кластера.' },
  { id: 5, time: '04:51', type: 'Опасность', zone: 'Запад', sources: 14, confidence: 88, tone: 'medium', text: 'Событие собрано в сюжет: сообщения совпадают по времени, но расходятся по деталям.' },
];

const FALLBACK_ZONES = [
  { name: 'Север', score: 34 },
  { name: 'Центр', score: 71 },
  { name: 'Восток', score: 86 },
  { name: 'Юг', score: 92 },
  { name: 'Запад', score: 58 },
  { name: 'Приграничье', score: 76 },
];

function Stat({ label, value, accent }) {
  return (
    <div className={styles.stat} data-accent={accent}>
      <div className={styles.statValue}>{value}</div>
      <div className={styles.statLabel}>{label}</div>
    </div>
  );
}

function intensityClass(score) {
  if (score >= 85) return styles.hot;
  if (score >= 70) return styles.warm;
  return styles.calm;
}

export function NewsScreen({ variant = 'summary' }) {
  const [topics, setTopics] = useState(FALLBACK_TOPICS);
  const [topic, setTopic] = useState(null);
  const [summary, setSummary] = useState(null);
  const [speed, setSpeed] = useState('16x');
  const [query, setQuery] = useState('');
  const [collecting, setCollecting] = useState(false);

  useEffect(() => {
    api.getNewsTopics()
      .then((rows) => {
        const next = rows.length ? rows : FALLBACK_TOPICS;
        setTopics(next);
        setTopic((cur) => cur || next[0]);
      })
      .catch(() => setTopic((cur) => cur || FALLBACK_TOPICS[0]));
  }, []);

  useEffect(() => {
    if (!topic?.id) {
      setSummary(null);
      return;
    }
    api.getNewsSummary(topic.id).then(setSummary).catch(() => setSummary(null));
  }, [topic?.id]);

  async function addTopicFromQuery() {
    const name = query.trim();
    if (!name) return;
    try {
      const created = await api.createNewsTopic(name, name);
      const rows = await api.getNewsTopics();
      setTopics(rows);
      setTopic(created);
      setQuery('');
    } catch (e) {
      console.warn('Failed to create news topic:', e.message);
    }
  }

  async function collectSelectedTopic() {
    if (!topic?.id || collecting) return;
    setCollecting(true);
    try {
      await api.collectNews(topic.id);
      setTimeout(async () => {
        try { setSummary(await api.getNewsSummary(topic.id)); } catch {}
        setCollecting(false);
      }, 2500);
    } catch {
      setCollecting(false);
    }
  }

  const events = summary?.events?.length ? summary.events : FALLBACK_EVENTS;
  const zones = summary?.zones?.length ? summary.zones : FALLBACK_ZONES;
  const stats = summary?.stats || { events: 248, sources: 91, clusters: 17, confidence: 82 };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return events;
    return events.filter((event) => `${event.type} ${event.zone} ${event.text}`.toLowerCase().includes(q));
  }, [events, query]);

  return (
    <div className={styles.wrap}>
      <section className={styles.controlBand}>
        <div className={styles.topicRow}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') addTopicFromQuery(); }}
            placeholder="Тема, регион, событие"
            className={styles.topicInput}
          />
          <div className={styles.topicChips}>
            {topics.map((item) => (
              <button key={item.id ?? item.name} data-active={topic?.name === item.name ? '1' : '0'} onClick={() => setTopic(item)}>
                {item.name}
              </button>
            ))}
          </div>
        </div>
        <div className={styles.replayBar}>
          <div className={styles.timeBlock}>
            <span>13 июн</span>
            <strong>03:00 - 05:00</strong>
          </div>
          <div className={styles.timeline}>
            <span style={{ width: '66%' }} />
          </div>
          <div className={styles.speedGroup}>
            <button data-active="0" onClick={collectSelectedTopic} disabled={!topic?.id || collecting}>
              {collecting ? 'Сбор...' : 'Собрать'}
            </button>
            {SPEEDS.map((item) => (
              <button key={item} data-active={speed === item ? '1' : '0'} onClick={() => setSpeed(item)}>
                {item}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className={styles.statsRow}>
        <Stat label="событий" value={String(stats.events)} accent="hot" />
        <Stat label="источников" value={String(stats.sources)} accent="warm" />
        <Stat label="кластеров" value={String(stats.clusters)} accent="calm" />
        <Stat label="доверие" value={`${stats.confidence}%`} accent="warm" />
      </section>

      <section className={styles.mainGrid}>
        <div className={styles.mapPanel}>
          <div className={styles.panelHead}>
            <div>
              <h2>{variant === 'sources' ? 'Источники и зоны' : topic?.name || 'Новости'}</h2>
              <p>События сгруппированы по зоне, типу и подтверждению источниками.</p>
            </div>
            <span className={styles.livePill}>LIVE</span>
          </div>
          <div className={styles.zoneGrid}>
            {zones.map(({ name, score }) => (
              <button key={name} className={`${styles.zoneCell} ${intensityClass(score)}`}>
                <span>{name}</span>
                <strong>{score}</strong>
              </button>
            ))}
          </div>
        </div>

        <div className={styles.feedPanel}>
          <div className={styles.panelHead}>
            <div>
              <h2>{variant === 'stories' ? 'Сюжеты' : 'Лента фиксаций'}</h2>
              <p>Ранние сигналы из Telegram, чатов и веб-источников.</p>
            </div>
          </div>
          <div className={styles.eventList}>
            {filtered.map((event) => (
              <article key={event.id} className={styles.event} data-tone={event.tone}>
                <div className={styles.eventTime}>{event.time}</div>
                <div className={styles.eventBody}>
                  <div className={styles.eventTopline}>
                    <span>{event.type}</span>
                    <span>{event.zone}</span>
                    <span>{event.sources} источн.</span>
                    <strong>{event.confidence}%</strong>
                  </div>
                  <p>{event.text}</p>
                </div>
              </article>
            ))}
            {filtered.length === 0 && <div className={styles.empty}>Пока нет событий по этой теме</div>}
          </div>
        </div>
      </section>
    </div>
  );
}
