import { useMemo, useState } from 'react';
import styles from './news.module.css';

const TOPICS = ['Военные действия', 'Геополитика', 'Экономика', 'Энергетика'];
const SPEEDS = ['1x', '4x', '16x', '40x'];

const EVENTS = [
  { id: 1, time: '03:18', type: 'БПЛА', zone: 'Юг', sources: 18, confidence: 91, tone: 'high', text: 'Рост сообщений о движении БПЛА из нескольких Telegram-каналов и локальных чатов.' },
  { id: 2, time: '03:42', type: 'ПВО', zone: 'Центр', sources: 12, confidence: 84, tone: 'medium', text: 'Синхронные сообщения о работе ПВО, подтверждение из независимых источников задерживается.' },
  { id: 3, time: '04:06', type: 'Взрывы', zone: 'Восток', sources: 9, confidence: 77, tone: 'high', text: 'Несколько каналов фиксируют взрывы, часть сообщений требует проверки географии.' },
  { id: 4, time: '04:27', type: 'Радар', zone: 'Север', sources: 7, confidence: 69, tone: 'low', text: 'Появился слабый сигнал по новым каналам, пока без устойчивого кластера.' },
  { id: 5, time: '04:51', type: 'Опасность', zone: 'Запад', sources: 14, confidence: 88, tone: 'medium', text: 'Событие собрано в сюжет: сообщения совпадают по времени, но расходятся по деталям.' },
];

const ZONES = [
  ['Север', 34], ['Центр', 71], ['Восток', 86], ['Юг', 92], ['Запад', 58], ['Приграничье', 76],
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
  const [topic, setTopic] = useState(TOPICS[0]);
  const [speed, setSpeed] = useState('16x');
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return EVENTS;
    return EVENTS.filter((event) => `${event.type} ${event.zone} ${event.text}`.toLowerCase().includes(q));
  }, [query]);

  return (
    <div className={styles.wrap}>
      <section className={styles.controlBand}>
        <div className={styles.topicRow}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Тема, регион, событие"
            className={styles.topicInput}
          />
          <div className={styles.topicChips}>
            {TOPICS.map((item) => (
              <button key={item} data-active={topic === item ? '1' : '0'} onClick={() => setTopic(item)}>
                {item}
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
            {SPEEDS.map((item) => (
              <button key={item} data-active={speed === item ? '1' : '0'} onClick={() => setSpeed(item)}>
                {item}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className={styles.statsRow}>
        <Stat label="событий" value="248" accent="hot" />
        <Stat label="источников" value="91" accent="warm" />
        <Stat label="кластеров" value="17" accent="calm" />
        <Stat label="доверие" value="82%" accent="warm" />
      </section>

      <section className={styles.mainGrid}>
        <div className={styles.mapPanel}>
          <div className={styles.panelHead}>
            <div>
              <h2>{variant === 'sources' ? 'Источники и зоны' : topic}</h2>
              <p>События сгруппированы по зоне, типу и подтверждению источниками.</p>
            </div>
            <span className={styles.livePill}>LIVE</span>
          </div>
          <div className={styles.zoneGrid}>
            {ZONES.map(([name, score]) => (
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
          </div>
        </div>
      </section>
    </div>
  );
}
