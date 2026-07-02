// Источники (Sources) — screen for managing curated TG channels/chats.
// Shows all /intel/sources grouped by side; allows add & delete.
import { useEffect, useState, useCallback } from 'react';
import { Icon } from '../../../core/components/icons';
import { intelApi, SIDE, DIRECTION_NAMES } from '../api';
import styles from '../intel.module.css';

const KIND_LABEL = { channel: 'КАНАЛ', chat: 'ЧАТ' };
// Области для пикера субъекта — ключи совпадают с seed.DEFAULT_DIRECTIONS / geo.py.
const DIR_OPTS = Object.entries(DIRECTION_NAMES).filter(([k]) => k !== 'unassigned');

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

// Радар-источник: его посты идут только в радарную ленту ситуационного центра.
function RadarBadge({ on, onToggle, busy }) {
  const color = on ? '#FFB23E' : '#4A6378';
  return (
    <span
      className={styles.srcBadge}
      style={{ color, background: on ? 'rgba(255,178,62,.12)' : 'rgba(74,99,120,.10)', border: `1px solid ${color}40`, cursor: busy ? 'wait' : 'pointer', opacity: busy ? 0.5 : 1 }}
      onClick={busy ? undefined : onToggle}
      title={on ? 'Радар: посты только в радарной ленте. Клик — снять флаг.' : 'Не радар. Клик — пометить радаром.'}
    >
      {busy ? '…' : '📡 РАДАР'}
    </span>
  );
}

// ── Discovery Modal ──────────────────────────────────────────────────────────

const SOURCE_LABEL = { search: 'Поиск', recommendation: 'Рекомендация', linked: 'Привязанный' };

function DiscoveryModal({ open, onClose, onAdded }) {
  const [step, setStep] = useState('pick');           // pick → search → results
  const [dirs, setDirs] = useState([]);                // available directions from API
  const [dirKey, setDirKey] = useState('');
  const [candidates, setCandidates] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [accepting, setAccepting] = useState(false);

  useEffect(() => {
    if (open) {
      intelApi.discoverDirections().then(d => setDirs(d || [])).catch(() => {});
    }
  }, [open]);

  function reset() {
    setStep('pick');
    setDirKey('');
    setCandidates([]);
    setSelected(new Set());
    setBusy(false);
    setErr('');
    setAccepting(false);
  }

  async function handleSearch() {
    if (!dirKey) return;
    setBusy(true);
    setErr('');
    setStep('search');
    try {
      const data = await intelApi.discover({ direction: dirKey });
      setCandidates(data.candidates || []);
      setStep('results');
    } catch (e) {
      setErr(e.message || 'Ошибка поиска');
      setStep('pick');
    } finally {
      setBusy(false);
    }
  }

  function toggleAll() {
    if (selected.size === candidates.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(candidates.map(c => c.handle)));
    }
  }

  function toggleOne(handle) {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(handle)) next.delete(handle); else next.add(handle);
      return next;
    });
  }

  async function handleAccept() {
    if (selected.size === 0 || accepting) return;
    setAccepting(true);
    setErr('');
    try {
      const items = candidates
        .filter(c => selected.has(c.handle))
        .map(c => ({
          handle: c.handle,
          kind: c.kind,
          subject: c.subject,
          direction: c.direction,
          side: c.direction ? (SIDE_MAP[c.direction] || 'ru') : 'ru',
        }));
      const data = await intelApi.discoverAccept({ items });
      onAdded?.(data.accepted || 0);
      reset();
    } catch (e) {
      setErr(e.message || 'Ошибка добавления');
    } finally {
      setAccepting(false);
    }
  }

  if (!open) return null;

  return (
    <div className={styles.discOverlay} onClick={e => { if (e.target === e.currentTarget) { reset(); onClose(); } }}>
      <div className={styles.discModal}>
        {/* Header */}
        <div className={styles.discHeader}>
          <span className={styles.discTitle}>
            <Icon name="search" size={14} color="#57D2E2" />
            Найти TG-чаты
          </span>
          <button className={styles.discClose} onClick={() => { reset(); onClose(); }}>✕</button>
        </div>

        {/* Step: Pick direction */}
        {step === 'pick' && (
          <div className={styles.discBody}>
            <label className={styles.discLabel}>Выберите направление</label>
            <div className={styles.discPickRow}>
              <select
                className={styles.srcSelect}
                value={dirKey}
                onChange={e => setDirKey(e.target.value)}
                style={{ flex: 1 }}
              >
                <option value="">— выбрать —</option>
                {dirs.map(d => (
                  <option key={d.key} value={d.key}>
                    {DIRECTION_NAMES[d.key] || d.key} ({d.cities.join(', ')})
                  </option>
                ))}
              </select>
              <button
                className={styles.discSearchBtn}
                disabled={!dirKey || busy}
                onClick={handleSearch}
              >
                {busy ? '…' : '🔍 Искать'}
              </button>
            </div>
            {err && <div className={styles.discErr}>{err}</div>}
          </div>
        )}

        {/* Step: Searching */}
        {step === 'search' && (
          <div className={styles.discBody} style={{ textAlign: 'center', padding: '40px 20px' }}>
            <div className={styles.discSpinner} />
            <div style={{ marginTop: 12, color: '#8DA3B8' }}>
              Ищем чаты по направлению «{DIRECTION_NAMES[dirKey] || dirKey}»…
            </div>
            <div style={{ marginTop: 4, fontSize: 12, color: '#4A6378' }}>
              Это может занять 10–30 секунд
            </div>
          </div>
        )}

        {/* Step: Results */}
        {step === 'results' && (
          <>
            <div className={styles.discResults}>
              <span>Найдено: <strong>{candidates.length}</strong></span>
              <span style={{ color: '#57D2E2' }}>
                Выбрано: <strong>{selected.size}</strong>
              </span>
            </div>

            <div className={styles.discTableWrap}>
              {/* Select all row */}
              <div className={`${styles.discRow} ${styles.discRowHead}`}>
                <input
                  type="checkbox"
                  checked={candidates.length > 0 && selected.size === candidates.length}
                  onChange={toggleAll}
                  disabled={accepting}
                />
                <span className={styles.discColHandle}>Канал/чат</span>
                <span className={styles.discColTitle}>Название</span>
                <span className={styles.discColCount}>Участников</span>
                <span className={styles.discColSource}>Источник</span>
              </div>
              <div className={styles.discTableBody}>
                {candidates.length === 0 ? (
                  <div className={styles.discEmpty}>Ничего не найдено для этого направления</div>
                ) : candidates.map(c => (
                  <div key={c.handle} className={`${styles.discRow} ${selected.has(c.handle) ? styles.discRowSelected : ''}`}>
                    <input
                      type="checkbox"
                      checked={selected.has(c.handle)}
                      onChange={() => toggleOne(c.handle)}
                      disabled={accepting}
                    />
                    <span className={styles.discColHandle}>{c.handle}</span>
                    <span className={styles.discColTitle} title={c.title}>{c.title}</span>
                    <span className={styles.discColCount}>{(c.participants || 0).toLocaleString('ru')}</span>
                    <span className={styles.discColSource}>{SOURCE_LABEL[c.source] || c.source}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Footer */}
            <div className={styles.discFooter}>
              {err && <span className={styles.discErr}>{err}</span>}
              <div className={styles.discFooterRight}>
                <button className={styles.discSearchBtn} onClick={() => { reset(); onClose(); }}>
                  Закрыть
                </button>
                <button
                  className={styles.discAcceptBtn}
                  disabled={selected.size === 0 || accepting}
                  onClick={handleAccept}
                >
                  {accepting ? '…' : `Добавить ${selected.size}`}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Map direction key → default side for discovery accept
const SIDE_MAP = {
  bryansk: 'ru', belgorod: 'ru', kursk: 'ru', voronezh: 'ru', oryel: 'ru',
  rostov: 'ru', crimea: 'ru', krasnodar: 'ru', smolensk: 'ru', pskov: 'ru',
  moscow: 'ru', dnr: 'ru', lnr: 'ru',
  kyiv: 'ua', kharkiv: 'ua', kherson: 'ua', zaporizhzhia: 'ua',
  dnipropetrovsk: 'ua', odesa: 'ua', mykolaiv: 'ua', chernihiv: 'ua', sumy: 'ua',
};


export function IntelSources() {
  const [sources, setSources]     = useState([]);
  const [loading, setLoading]     = useState(true);
  const [sideFilter, setSideFilter] = useState('all');
  const [radarFilter, setRadarFilter] = useState('all'); // all | radar | plain
  const [query, setQuery]         = useState('');

  // Add-form state
  const [link, setLink]       = useState('');
  const [side, setSide]       = useState('ru');
  const [kind, setKind]       = useState('channel');
  const [subject, setSubject] = useState('');
  const [direction, setDirection] = useState('');
  const [isRadar, setIsRadar] = useState(false);
  const [adding, setAdding]   = useState(false);
  const [deleting, setDeleting] = useState(null); // id being deleted
  const [toggling, setToggling] = useState(null); // id whose kind is being switched
  const [editing, setEditing] = useState(null);   // {id, subject, direction} строки в режиме правки
  const [savingEdit, setSavingEdit] = useState(false);
  const [err, setErr]         = useState('');
  const [showDiscover, setShowDiscover] = useState(false);

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
      await intelApi.addSource({ link: link.trim(), side, kind, subject: subject.trim(), direction, is_radar: isRadar });
      setLink('');
      setSubject('');
      setIsRadar(false);
      await load();
    } catch (e) {
      setErr(e.message || 'Ошибка добавления');
    } finally {
      setAdding(false);
    }
  }

  async function handleToggleRadar(src) {
    if (toggling) return;
    const next = !src.is_radar;
    setToggling(src.id);
    try {
      const updated = await intelApi.updateSource(src.id, { is_radar: next });
      setSources(prev => prev.map(s =>
        s.id === src.id ? { ...s, ...(updated && updated.id ? updated : { is_radar: next }) } : s
      ));
    } catch (e) {
      setErr(e.message || 'Ошибка смены радар-флага');
    } finally {
      setToggling(null);
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
      // Убираем строку на месте, без load() — иначе список перерисуется
      // и скролл прыгнет наверх, теряя позицию пользователя.
      setSources(prev => prev.filter(s => s.id !== id));
    } catch (e) {
      setErr(e.message || 'Ошибка удаления');
    } finally {
      setDeleting(null);
    }
  }

  async function handleSaveEdit() {
    if (!editing || savingEdit) return;
    setSavingEdit(true);
    try {
      const updated = await intelApi.updateSource(editing.id, {
        subject: editing.subject.trim(),
        direction: editing.direction,
      });
      setSources(prev => prev.map(s => (s.id === editing.id ? { ...s, ...updated } : s)));
      setEditing(null);
    } catch (e) {
      setErr(e.message || 'Ошибка сохранения');
    } finally {
      setSavingEdit(false);
    }
  }

  const sides = ['all', ...Object.keys(SIDE)];
  const q = query.trim().toLowerCase();
  const visible = sources.filter(s =>
    (sideFilter === 'all' || s.side === sideFilter) &&
    (radarFilter === 'all' || (radarFilter === 'radar' ? !!s.is_radar : !s.is_radar)) &&
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
          <button
            className={styles.discTriggerBtn}
            onClick={() => setShowDiscover(true)}
            title="Автоматический поиск TG-чатов и каналов"
          >
            🔍 Найти чаты
          </button>
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
            <span style={{ width: 8 }} />
            {[['all', 'ВСЕ ТИПЫ'], ['radar', '📡 РАДАРЫ'], ['plain', 'ОБЫЧНЫЕ']].map(([k, label]) => (
              <button
                key={k}
                className={styles.filterChip}
                data-active={radarFilter === k ? '1' : '0'}
                onClick={() => setRadarFilter(k)}
              >
                {label}
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
          <input
            className={styles.srcInput}
            placeholder="нас. пункт (напр. Шебекино)"
            value={subject}
            onChange={e => setSubject(e.target.value)}
            disabled={adding}
            style={{ flex: '0 1 160px' }}
          />
          <select
            className={styles.srcSelect}
            value={direction}
            onChange={e => setDirection(e.target.value)}
            disabled={adding}
            title="Область (fallback для кластеризации)"
          >
            <option value="">— область —</option>
            {DIR_OPTS.map(([k, name]) => (
              <option key={k} value={k}>{name}</option>
            ))}
          </select>
          <label
            title="Радар-источник: посты только в радарной ленте ситуационного центра"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: isRadar ? '#FFB23E' : '#8DA3B8', cursor: 'pointer', whiteSpace: 'nowrap' }}
          >
            <input
              type="checkbox"
              checked={isRadar}
              onChange={e => setIsRadar(e.target.checked)}
              disabled={adding}
            />
            📡 радар
          </label>
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
            visible.map(src => {
              const isEditing = editing && editing.id === src.id;
              return (
              <div key={src.id} className={styles.srcRow}>
                <SideBadge side={src.side} />
                <KindBadge kind={src.kind} busy={toggling === src.id} onToggle={() => handleToggleKind(src)} />
                <RadarBadge on={!!src.is_radar} busy={toggling === src.id} onToggle={() => handleToggleRadar(src)} />
                <span className={styles.srcHandle}>
                  {src.handle || src.id}
                </span>
                {isEditing ? (
                  <>
                    <input
                      className={styles.srcInput}
                      placeholder="нас. пункт"
                      value={editing.subject}
                      onChange={e => setEditing({ ...editing, subject: e.target.value })}
                      style={{ flex: '0 1 130px' }}
                      autoFocus
                    />
                    <select
                      className={styles.srcSelect}
                      value={editing.direction}
                      onChange={e => setEditing({ ...editing, direction: e.target.value })}
                    >
                      <option value="">— область —</option>
                      {DIR_OPTS.map(([k, name]) => (
                        <option key={k} value={k}>{name}</option>
                      ))}
                    </select>
                    <button className={styles.srcDel} onClick={handleSaveEdit} disabled={savingEdit} title="Сохранить" style={{ color: '#34D8A0' }}>✓</button>
                    <button className={styles.srcDel} onClick={() => setEditing(null)} title="Отмена">✕</button>
                  </>
                ) : (
                  <>
                    <span
                      className={styles.srcMeta}
                      onClick={() => setEditing({ id: src.id, subject: src.subject || '', direction: src.direction || '' })}
                      title="Изменить нас. пункт / область"
                      style={{ cursor: 'pointer', color: src.subject ? '#57D2E2' : '#4A6378' }}
                    >
                      {src.subject ? `📍 ${src.subject}` : '📍 —'}
                      {src.direction ? ` · ${DIRECTION_NAMES[src.direction] || src.direction}` : ''}
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
                  </>
                )}
              </div>
              );
            })
          )}
        </div>
      </div>

      {/* Discovery modal */}
      <DiscoveryModal
        open={showDiscover}
        onClose={() => setShowDiscover(false)}
        onAdded={(count) => { if (count > 0) load(); }}
      />
    </div>
  );
}
