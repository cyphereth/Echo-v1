// Probes screen (brand) — AI-настройка зондов + список активных.
// Канон: project/ui_kits/app/probes.jsx. Зонды на бэкенде пересобираются из
// keywords/hashtags/competitors/niche через POST /brands/{id}/config — поэтому
// AI-чипы добавляем в keywords и сохраняем конфиг; список читаем из brand.probes.
import { useState } from 'react';
import { Icon } from '../../../core/components/icons';
import { Button, Eyebrow } from '../../../core/components/ui';
import * as api from '../api';
import styles from '../../../components/app/probes.module.css';

const KIND_LABEL = { keyword: 'Ключевое', hashtag: 'Хэштег', mention: 'Упоминание', channel: 'TG-канал', chat: 'Чат', chat_linked: 'Чат' };
const PLATFORM_COLOR = { instagram: '#E1306C', tiktok: 'var(--fg-2)', telegram: '#29A9EB' };

export function ProbesScreen({ brand, onBrandSaved }) {
  const [suggested, setSuggested]   = useState([]);
  const [added, setAdded]           = useState(new Set());
  const [analyzing, setAnalyzing]   = useState(false);
  const [urlInput, setUrlInput]     = useState('');
  const [error, setError]           = useState('');
  const [saving, setSaving]         = useState(false);

  // AI-разбор: /brands/suggest отдаёт полный конфиг, берём оттуда keywords+hashtags
  async function analyze() {
    const name = urlInput.trim().replace(/^https?:\/\//, '').replace(/\/.*$/, '');
    const target = name || brand?.name;
    if (!target) return;
    setAnalyzing(true); setError(''); setSuggested([]);
    try {
      const cfg = await api.suggestBrand(target);
      const kws = [
        ...(cfg.keywords || []),
        ...(cfg.hashtags || []).map(h => h.startsWith('#') ? h : '#' + h),
        ...(cfg.niche_keywords || []),
      ].filter(Boolean);
      const unique = [...new Set(kws)].slice(0, 12);
      setSuggested(unique);
      setAdded(new Set());
    } catch (e) {
      setError(String(e.message || e).includes('503') ? 'AI недоступен — задайте ключ LLM_API_KEY' : 'Не удалось разобрать бренд');
    } finally {
      setAnalyzing(false);
    }
  }

  // добавить чип → помечаем; сохраняем все добавленные как keywords через config
  function toggleChip(q) {
    setAdded(prev => {
      const next = new Set(prev);
      if (next.has(q)) next.delete(q);
      else next.add(q);
      return next;
    });
  }

  async function applyAdded() {
    if (!brand || added.size === 0) return;
    setSaving(true); setError('');
    try {
      const newKeywords = [...new Set([...(brand.keywords || []), ...added])];
      await api.updateBrandConfig(brand.id, { keywords: newKeywords });
      // перечитываем бренд, чтобы получить обновлённые зонды
      const updated = await api.getBrand(brand.id);
      onBrandSaved(updated);
      setAdded(new Set());
      setSuggested([]);
    } catch {
      setError('Не удалось сохранить зонды');
    } finally {
      setSaving(false);
    }
  }

  async function deleteProbe(probe) {
    // chat/chat_linked зонды — авто-обнаруженные, не трогаем через config.
    // keyword/hashtag зонды восстанавливаются из keywords → убрать запрос из keywords.
    if (['chat', 'chat_linked'].includes(probe.kind)) return;
    const q = probe.query;
    const remaining = (brand.keywords || []).filter(k => k !== q && k !== q.replace(/^#/, ''));
    setSaving(true);
    try {
      await api.updateBrandConfig(brand.id, { keywords: remaining });
      const updated = await api.getBrand(brand.id);
      onBrandSaved(updated);
    } catch { setError('Не удалось удалить зонд'); }
    finally { setSaving(false); }
  }

  const probes = brand?.probes || [];

  return (
    <div className={styles.wrap}>
      <div className={styles.inner}>
        {/* intro */}
        <div className={styles.intro}>
          <h2>Зонды</h2>
          <p>
            Зонд — это поисковый запрос по ключевому слову или хэштегу, которым Echo Radar
            непрерывно ищет упоминания <b>{brand?.name || 'бренда'}</b> в Instagram и TikTok.
            Чем точнее зонды — тем меньше шума и точнее severity.
          </p>
        </div>

        {/* AI onboarding */}
        <div className={styles.onb}>
          <div className={styles.onbHead}>
            <span className={styles.onbIc}><Icon name="sparkles" size={16} color="var(--brand-bright)" /></span>
            <div>
              <div className={styles.onbTitle}>AI-настройка зондов</div>
              <div className={styles.onbSub}>Дайте ссылку или название — предложим ключевые слова и хэштеги</div>
            </div>
          </div>
          <div className={styles.onbInput}>
            <Icon name="link" size={15} color="var(--fg-3)" />
            <input
              value={urlInput}
              onChange={e => setUrlInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && analyze()}
              placeholder={brand?.name ? brand.name : 'papapizza.ru или название'}
            />
            <Button variant="primary" size="sm" icon="sparkles" onClick={analyze} disabled={analyzing}>
              {analyzing ? 'Разбираю…' : 'Разобрать'}
            </Button>
          </div>
          {error && <div style={{ color: 'var(--sev-critical-bright)', fontSize: 12.5, marginTop: 10 }}>{error}</div>}
          {suggested.length > 0 && (
            <>
              <Eyebrow style={{ display: 'block', margin: '16px 0 10px' }}>
                Предложено AI — подтвердите нужные
              </Eyebrow>
              <div className={styles.chips}>
                {suggested.map(q => (
                  <button key={q} className={styles.chip} data-added={added.has(q) ? '1' : '0'} onClick={() => toggleChip(q)}>
                    <Icon name={added.has(q) ? 'check' : 'plus'} size={13} />{q}
                  </button>
                ))}
              </div>
              {added.size > 0 && (
                <div style={{ marginTop: 14 }}>
                  <Button variant="primary" size="sm" icon="check" onClick={applyAdded} disabled={saving}>
                    {saving ? 'Сохраняю…' : `Добавить ${added.size} ${added.size === 1 ? 'зонд' : 'зондов'}`}
                  </Button>
                </div>
              )}
            </>
          )}
        </div>

        {/* active probes */}
        <div className={styles.list}>
          <div className={styles.listHead}>
            <span className={styles.listHeadTitle}>
              <Icon name="radio" size={16} color="var(--brand-bright)" />
              Активные зонды
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700, color: 'var(--brand-bright)', background: 'var(--brand-ghost)', padding: '2px 8px', borderRadius: 'var(--r-pill)' }}>
                {probes.length}
              </span>
            </span>
          </div>
          {probes.length === 0 ? (
            <div className={styles.empty}>
              Зондов пока нет. Настройте ключевые слова выше или в «Настройках».
            </div>
          ) : (
            probes.map(p => (
              <div key={p.id} className={styles.row}>
                <span className={styles.kind}>{KIND_LABEL[p.kind] || p.kind}</span>
                <span className={styles.query}>{p.query}</span>
                <span className={styles.platforms}>
                  <Icon name={p.platform} size={15} color={PLATFORM_COLOR[p.platform] || 'var(--fg-3)'} />
                </span>
                <span className={styles.source}>{p.source}</span>
                {!['chat', 'chat_linked'].includes(p.kind) && (
                  <button className={styles.rowDel} onClick={() => deleteProbe(p)} title="Удалить зонд">
                    <Icon name="x" size={14} color="var(--fg-4)" />
                  </button>
                )}
              </div>
            ))
          )}
          {saving && <div className={styles.loading}>Сохранение…</div>}
        </div>
      </div>
    </div>
  );
}
