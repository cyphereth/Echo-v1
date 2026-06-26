// Источники (Sources) — screen for managing curated TG channels/chats.
// Shows all /intel/sources grouped by side; allows add & delete.
import { useEffect, useState } from 'react';
import { Icon } from '../../../core/components/icons';
import { intelApi, SIDE } from '../api';
import styles from '../intel.module.css';

const KIND_LABEL = { channel: 'КАНАЛ', chat: 'ЧАТ' };

function SideBadge({ side }) {
  const info = SIDE[side] || { label: side?.toUpperCase() || '?', color: '#6A8499' };
  return (
    <span
      className={styles.srcBadge}
      style={{ color: info.color, background: info.color + '1A', border: `1px solid ${info.color}40` }}
    >
      {info.label}
    </span>
  );
}

function KindBadge({ kind, onToggle, busy }) {
  return (
    <span
      className={styles.srcBadge}
      style={{ color: '#8DA3B8', background: 'rgba(141,163,184,.10)', border: '1px solid rgba(141,163,184,.18)', cursor: busy ? 'wait' : 'pointer', opacity: busy ? 0.5 : 1 }}
      onClick={busy ? undefined : onToggle}
      title="Сменить тип (Канал ⇄ Чат)"
    >
      {busy ? '…' : (KIND_LABEL[kind] || kind)}
    </span>
  );
}

export function IntelSources() {
  const [sources, setSources]     = useState([]);
  const [loading, setLoading]     = useState(true);
  const [sideFilter, setSideFilter] = useState('all');
  const [query, setQuery]         = useState('');

  // Add-form state
  const [link, setLink]       = useState('');
  const [side, setSide]       = useState('ru');
  const [kind, setKind]       = useState('channel');
  const [adding, setAdding]   = useState(false);
  const [deleting, setDeleting] = useState(null); // id being deleted
  const [toggling, setToggling] = useState(null); // id whose kind is being switched
  const [err, setErr]         = useState('');

  async function load() {
    setLoading(true);
    try {
      const data = await intelApi.sources();
      setSources(Array.isArray(data) ? data : []);
    } catch (e) {
      setSources([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function handleAdd(e) {
    e.preventDefault();
    if (!link.trim()) { setErr('Введите ссылку или @handle'); return; }
    setErr('');
    setAdding(true);
    try {
      await intelApi.addSource({ link: link.trim(), side, kind });
      setLink('');
      await load();
    } catch (e) {
      setErr(e.message || 'Ошибка добавления');
    } finally {
      setAdding(false);
    }
  }

  async function handleToggleKind(src) {
    if (toggling) return;
    const next = src.kind === 'chat' ? 'channel' : 'chat';
    setToggling(src.id);
    try {
      const updated = await intelApi.updateSource(src.id, { kind: next });
      // Обновляем элемент на месте, без load() — иначе список перерисуется
      // и скролл прыгнет наверх, теряя позицию пользователя.
      setSources(prev => prev.map(s =>
        s.id === src.id ? { ...s, ...(updated && updated.id ? updated : { kind: next }) } : s
      ));
    } catch (e) {
      setErr(e.message || 'Ошибка смены типа');
    } finally {
      setToggling(null);
    }
  }

  async function handleDelete(id) {
    if (deleting) return;
    setDeleting(id);
    try {
      await intelApi.deleteSource(id);
      await load();
    } catch (e) {
      setErr(e.message || 'Ошибка удаления');
    } finally {
      setDeleting(null);
    }
  }

  const sides = ['all', ...Object.keys(SIDE)];
  const q = query.trim().toLowerCase();
  const visible = sources.filter(s =>
    (sideFilter === 'all' || s.side === sideFilter) &&
    (!q || String(s.handle || s.id).toLowerCase().includes(q))
  );

  return (
    <div className={styles.workspace}>
      <div className={styles.section}>
        {/* Header */}
        <div className={styles.srcHeader}>
          <span className={styles.sectionTitle}>
            <Icon name="link" size={13} color="#57D2E2" />
            Источники
            <span className={styles.sectionCount}>{sources.length}</span>
          </span>
          <div className={styles.srcFilters}>
            {sides.map(s => (
              <button
                key={s}
                className={styles.filterChip}
                data-active={sideFilter === s ? '1' : '0'}
                onClick={() => setSideFilter(s)}
              >
                {s === 'all' ? 'ВСЕ' : (SIDE[s]?.label || s.toUpperCase())}
              </button>
            ))}
          </div>
        </div>

        {/* Add form — наверху, чтобы не скроллить вниз после каждого добавления */}
        <form className={styles.srcAddForm} onSubmit={handleAdd}>
          <input
            className={styles.srcInput}
            placeholder="https://t.me/channel или @handle"
            value={link}
            onChange={e => { setLink(e.target.value); setErr(''); }}
            disabled={adding}
          />
          <select
            className={styles.srcSelect}
            value={side}
            onChange={e => setSide(e.target.value)}
            disabled={adding}
          >
            {Object.entries(SIDE).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>
          <select
            className={styles.srcSelect}
            value={kind}
            onChange={e => setKind(e.target.value)}
            disabled={adding}
          >
            <option value="channel">Канал</option>
            <option value="chat">Чат</option>
          </select>
          <button
            type="submit"
            className={styles.srcAddBtn}
            disabled={adding}
          >
            {adding ? '…' : '+ Добавить'}
          </button>
          {err && <span className={styles.srcError}>{err}</span>}
        </form>

        {/* Search box — найти источник для удаления без листания */}
        <div className={styles.srcSearch}>
          <Icon name="search" size={13} color="#4A6378" />
          <input
            placeholder="поиск по добавленным источникам…"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          {query && (
            <button type="button" className={styles.srcSearchClear} onClick={() => setQuery('')} title="Очистить">✕</button>
          )}
        </div>

        {/* Source list */}
        <div className={styles.sectionBody}>
          {loading ? (
            <div className={styles.empty}>Загрузка…</div>
          ) : visible.length === 0 ? (
            <div className={styles.empty}>{q ? 'Ничего не найдено по запросу.' : 'Источники не найдены.'}</div>
          ) : (
            visible.map(src => (
              <div key={src.id} className={styles.srcRow}>
                <SideBadge side={src.side} />
                <KindBadge kind={src.kind} busy={toggling === src.id} onToggle={() => handleToggleKind(src)} />
                <span className={styles.srcHandle}>
                  {src.handle || src.id}
                </span>
                <span className={styles.srcMeta}>
                  {src.last_collected
                    ? new Date(src.last_collected).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
                    : '—'}
                </span>
                <button
                  className={styles.srcDel}
                  onClick={() => handleDelete(src.id)}
                  disabled={deleting === src.id}
                  title="Удалить"
                >
                  ✕
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
