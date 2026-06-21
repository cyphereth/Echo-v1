import { useState, useEffect } from 'react';
import { Icon } from '../../../core/components/icons';
import * as api from '../api';
import styles from '../../../components/app/cityexplorer.module.css';

export function CityExplorerScreen() {
  const [city, setCity]         = useState('');
  const [report, setReport]     = useState(null);
  const [loading, setLoading]   = useState(false);
  const [collecting, setCollecting] = useState(null); // city being collected in background
  const [error, setError]       = useState('');
  const [history, setHistory]   = useState([]);

  const loadHistory = () => api.getCityReports().then(d => Array.isArray(d) && setHistory(d)).catch(() => {});
  useEffect(() => { loadHistory(); }, []);

  // Poll history every 5s while background collection is running
  useEffect(() => {
    if (!collecting) return;
    const iv = setInterval(() => {
      api.getCityReports().then(d => {
        if (!Array.isArray(d)) return;
        setHistory(d);
        const done = d.find(h => h.city === collecting);
        if (done) {
          // Report ready — fetch full report (cached hit now)
          api.exploreCity(done.display_city, false)
            .then(r => { if (r.cached || r.summary) { setReport(r); setCity(r.display_city); } })
            .catch(() => {});
          setCollecting(null);
          setLoading(false);
        }
      }).catch(() => {});
    }, 5000);
    return () => clearInterval(iv);
  }, [collecting]);

  async function run(targetCity, refresh = false) {
    const c = (targetCity ?? city).trim();
    if (!c) return;
    setLoading(true); setError(''); setReport(null);
    try {
      const r = await api.exploreCity(c, refresh);
      if (r.status === 'collecting') {
        // Background job started — poll until ready
        const { normalize } = { normalize: (s) => s.trim().toLowerCase() };
        setCollecting(normalize(c));
        setCity(c);
      } else {
        setReport(r); setCity(r.display_city || c);
        setLoading(false);
        loadHistory();
      }
    } catch (e) {
      setError('Не удалось запустить сбор — проверь подключение к серверу.');
      setLoading(false);
    }
  }

  const s = report?.summary || {};
  return (
    <div className={styles.page}>
      <div className={styles.searchBar}>
        <input className={styles.input} placeholder="Введите город — напр. Москва"
          value={city} onChange={e => setCity(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && run()} />
        <button className={styles.btnPrimary} onClick={() => run()} disabled={loading}>
          <Icon name="sparkles" size={14} />{collecting ? 'Собираю данные…' : loading ? 'Запускаю…' : 'Исследовать'}
        </button>
        {report && (
          <button className={styles.btnGhost} onClick={() => run(report.display_city, true)} disabled={loading}>
            <Icon name="zap" size={14} />Обновить
          </button>
        )}
      </div>
      {error && <div className={styles.error}>{error}</div>}
      <div className={styles.body}>
        <div className={styles.main}>
          {collecting ? (
            <div className={styles.collecting}>
              <Icon name="sparkles" size={28} />
              <div>Собираем посты и строим сводку для <strong>{city}</strong>…</div>
              <div style={{ fontSize: 12, color: 'var(--fg-4)', marginTop: 4 }}>Обычно 30–60 секунд</div>
            </div>
          ) : report ? (
            <>
              <div className={styles.metaRow}>
                <span className={styles.cityName}>{report.display_city}</span>
                <span className={styles.meta}>{report.post_count} постов · {(report.platforms || []).join(', ')}
                  {report.cached ? ' · из кеша' : ''}{report.created_at ? ` · ${new Date(report.created_at).toLocaleDateString('ru-RU')}` : ''}</span>
              </div>
              {s.overview && <div className={styles.overview}>{s.overview}</div>}
              {s.sentiment?.overall && (
                <div className={styles.sentiment} data-tone={s.sentiment.overall}>
                  Настроение: {s.sentiment.overall}{s.sentiment.note ? ` — ${s.sentiment.note}` : ''}
                </div>
              )}
              {Array.isArray(s.themes) && s.themes.length > 0 && (
                <section className={styles.section}><h3>Темы</h3>
                  <div className={styles.themeGrid}>
                    {s.themes.map((t, i) => (
                      <div key={i} className={styles.themeCard}>
                        <div className={styles.themeTitle}>{t.title}</div>
                        <div className={styles.themeDesc}>{t.description}</div>
                      </div>
                    ))}
                  </div>
                </section>
              )}
              {Array.isArray(s.wants) && s.wants.length > 0 && (
                <section className={styles.section}><h3>Что хотят / ищут</h3>
                  <ul className={styles.list}>{s.wants.map((w, i) => <li key={i}>{w}</li>)}</ul>
                </section>
              )}
              {Array.isArray(s.trends) && s.trends.length > 0 && (
                <section className={styles.section}><h3>Тренды</h3>
                  <ul className={styles.list}>{s.trends.map((t, i) => <li key={i}>{t}</li>)}</ul>
                </section>
              )}
              {Array.isArray(s.top_hashtags) && s.top_hashtags.length > 0 && (
                <div className={styles.tags}>{s.top_hashtags.map((h, i) => <span key={i} className={styles.tag}>{h}</span>)}</div>
              )}
            </>
          ) : (
            <div className={styles.empty}>Введите город, чтобы увидеть интересы аудитории.</div>
          )}
        </div>
        <aside className={styles.history}>
          <div className={styles.historyTitle}>История</div>
          {history.map(h => (
            <button key={h.city} className={styles.historyItem} onClick={() => run(h.display_city)}>
              {h.display_city}<span className={styles.historyMeta}>{h.post_count}</span>
            </button>
          ))}
        </aside>
      </div>
    </div>
  );
}
