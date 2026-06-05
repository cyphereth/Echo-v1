import { useState } from 'react';
import * as api from '../../services/api';
import styles from './aiwizard.module.css';

/**
 * AIWizard — 2-step brand setup wizard.
 * mode="create" → fullscreen onboarding, calls POST /onboarding
 * mode="edit"   → modal overlay, calls POST /brands/:id/config
 */
export function AIWizard({ mode, brand, onSaved, onClose }) {
  const [step, setStep]             = useState(mode === 'edit' ? 1 : 0);
  const [name, setName]             = useState(brand?.name ?? '');
  const [keywords, setKeywords]     = useState(brand?.keywords ?? []);
  const [hashtags, setHashtags]     = useState(brand?.hashtags ?? []);
  const [competitors, setCompetitors] = useState(brand?.competitors ?? []);
  const [niche, setNiche]           = useState(brand?.niche_keywords ?? []);
  const [previews, setPreviews]     = useState([]);
  const [tiktokUrl, setTiktokUrl]   = useState('');
  const [instagramUrl, setInstagramUrl] = useState('');
  const [voiceDescription, setVoiceDescription] = useState('');
  const [toneExamples, setToneExamples] = useState(brand?.tone_examples ?? []);
  const [audience, setAudience]     = useState(null);
  const [market, setMarket]         = useState(brand?.market ?? 'global');
  const [sphere, setSphere]         = useState(brand?.sphere ?? '');
  const [geo, setGeo]               = useState(brand?.geo ?? '');
  const [categoryTerms, setCategoryTerms] = useState(brand?.category_terms ?? []);
  const [audienceTerms, setAudienceTerms] = useState(brand?.audience_terms ?? []);
  const [followers, setFollowers]   = useState(brand?.followers ?? 0);
  const [localMode, setLocalMode]   = useState(brand?.local_mode ?? false);
  const [scanning, setScanning]     = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving]         = useState(false);
  const [toast, setToast]           = useState('');

  function showToast(msg) {
    setToast(msg);
    setTimeout(() => setToast(''), 4000);
  }

  async function handleSuggest() {
    if (!name.trim()) return;
    setSuggesting(true);
    setToast('');
    try {
      const data = await api.suggestBrand(name.trim());
      if (data.keywords?.length)       setKeywords(data.keywords);
      if (data.hashtags?.length)       setHashtags(data.hashtags);
      if (data.competitors?.length)    setCompetitors(data.competitors);
      if (data.niche_keywords?.length) setNiche(data.niche_keywords);
      if (data.market)                 setMarket(data.market);
      if (data.sphere)                 setSphere(data.sphere);
      if (data.geo)                    setGeo(data.geo);
      if (data.category_terms?.length) setCategoryTerms(data.category_terms);
      if (data.audience_terms?.length) setAudienceTerms(data.audience_terms);
      if (!data.keywords?.length && !data.competitors?.length) {
        showToast('AI не смог подобрать автоматически — заполните вручную.');
      }
    } catch {
      showToast('AI недоступен — заполните поля вручную и нажмите «Далее».');
    } finally {
      setSuggesting(false);
    }
  }

  async function handleScan() {
    if (!tiktokUrl.trim() && !instagramUrl.trim()) return;
    setScanning(true);
    setToast('');
    try {
      const data = await api.scanProfile(tiktokUrl.trim(), instagramUrl.trim());
      if (data.name)                   setName(data.name);
      if (data.keywords?.length)       setKeywords(data.keywords);
      if (data.hashtags?.length)       setHashtags(data.hashtags);
      if (data.competitors?.length)    setCompetitors(data.competitors);
      if (data.niche_keywords?.length) setNiche(data.niche_keywords);
      if (data.tone_examples?.length)  setToneExamples(data.tone_examples);
      if (data.voice_description)      setVoiceDescription(data.voice_description);
      if (data.audience_sentiment)     setAudience(data.audience_sentiment);
      if (data.market)                 setMarket(data.market);
      if (data.sphere)                 setSphere(data.sphere);
      if (data.geo)                    setGeo(data.geo);
      if (data.category_terms?.length) setCategoryTerms(data.category_terms);
      if (data.audience_terms?.length) setAudienceTerms(data.audience_terms);
      if (typeof data.followers === 'number') setFollowers(data.followers);
      // auto local mode: small account + a city
      if (data.geo && data.followers > 0 && data.followers <= 1000) setLocalMode(true);
      setStep(1);
    } catch (e) {
      const msg = String(e.message || '');
      if (msg.includes('422')) {
        showToast('Не удалось прочитать аккаунты — заполните вручную по названию.');
      } else {
        showToast('Ошибка анализа аккаунтов — попробуйте ручной режим.');
      }
    } finally {
      setScanning(false);
    }
  }

  async function handlePreview() {
    if (keywords.length === 0) { setStep(2); return; }
    setPreviewing(true);
    setToast('');
    try {
      const data = await api.previewBrand(keywords.slice(0, 2));
      setPreviews(data.posts ?? []);
    } catch {
      showToast('Превью недоступно — но можно сохранить без него.');
      setPreviews([]);
    } finally {
      setPreviewing(false);
      setStep(2);
    }
  }

  async function handleSave() {
    if (!name.trim()) return;
    setSaving(true);
    try {
      let result;
      if (mode === 'create') {
        result = await api.createBrand(name.trim(), keywords, hashtags, competitors, niche, toneExamples, market, sphere, geo, categoryTerms, audienceTerms, followers, localMode);
        api.collectBrand(result.id).catch(() => {});
      } else {
        await api.updateBrandConfig(brand.id, {
          name: name.trim(), keywords, hashtags,
          exclusions: brand.exclusions ?? [],
          competitors, niche_keywords: niche,
          tone_examples: toneExamples, market, sphere, geo, category_terms: categoryTerms,
          audience_terms: audienceTerms, followers, local_mode: localMode,
        });
        result = { ...brand, name: name.trim(), keywords, hashtags, competitors, niche_keywords: niche, tone_examples: toneExamples, market, sphere, geo, category_terms: categoryTerms, audience_terms: audienceTerms, followers, local_mode: localMode };
      }
      onSaved?.(result);
    } catch (e) {
      showToast(`Ошибка сохранения: ${e.message}`);
    } finally {
      setSaving(false);
    }
  }

  function removeTag(list, setList, tag) {
    setList(list.filter(t => t !== tag));
  }

  function TagGroup({ label, list, setList }) {
    return (
      <div className={styles.section}>
        <div className={styles.sectionLabel}>{label}</div>
        <div className={styles.tags}>
          {list.length === 0
            ? <span className={styles.empty}>Пусто</span>
            : list.map(t => (
              <span key={t} className={styles.tag}>
                {t}
                <button className={styles.tagX} onClick={() => removeTag(list, setList, t)}>✕</button>
              </span>
            ))}
        </div>
      </div>
    );
  }

  const inner = (
    <>
      <div className={styles.header}>
        <div className={styles.title}>
          {mode === 'create' ? '✨ Настройка бренда' : '✨ AI-заполнение'}
        </div>
        <div className={styles.sub}>
          {step === 0
            ? 'Введите ссылки на аккаунты бренда — Echo проанализирует контент'
            : step === 1
            ? 'Проверьте профиль бренда перед запуском'
            : 'Реальные посты по вашим ключевым словам'}
        </div>
      </div>

      {step === 0 && (
        <>
          <div className={styles.section}>
            <div className={styles.sectionLabel}>TikTok аккаунт</div>
            <input
              className={styles.nameInput}
              value={tiktokUrl}
              onChange={e => setTiktokUrl(e.target.value)}
              placeholder="@ozon или ссылка"
              autoFocus
            />
          </div>
          <div className={styles.section}>
            <div className={styles.sectionLabel}>Instagram аккаунт</div>
            <input
              className={styles.nameInput}
              value={instagramUrl}
              onChange={e => setInstagramUrl(e.target.value)}
              placeholder="@ozon.ru или ссылка"
            />
          </div>

          {toast && <div className={styles.toast}>{toast}</div>}

          <div style={{ fontSize: 12, color: 'var(--fg-4)' }}>
            Echo прочитает посты и комментарии, чтобы понять голос бренда и темы
          </div>

          <div className={styles.actions}>
            <button className={styles.cancelBtn} onClick={() => setStep(1)}>
              Заполнить вручную по названию →
            </button>
            <button
              className={styles.nextBtn}
              onClick={handleScan}
              disabled={scanning || (!tiktokUrl.trim() && !instagramUrl.trim())}
            >
              {scanning ? <><span className={styles.spinner} />Анализирую аккаунты…</> : 'Анализировать аккаунты'}
            </button>
          </div>
        </>
      )}

      {step === 1 && (
        <>
          <div className={styles.nameRow}>
            <input
              className={styles.nameInput}
              value={name}
              onChange={e => setName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSuggest()}
              placeholder="Название бренда (например: Ozon)"
              autoFocus
            />
            <button
              className={styles.suggestBtn}
              onClick={handleSuggest}
              disabled={!name.trim() || suggesting}
            >
              {suggesting ? <><span className={styles.spinner} />Подбираю…</> : 'Подобрать'}
            </button>
          </div>

          {toast && <div className={styles.toast}>{toast}</div>}

          <TagGroup label="Ключевые слова" list={keywords}    setList={setKeywords} />
          <TagGroup label="Хэштеги"        list={hashtags}    setList={setHashtags} />
          <TagGroup label="Конкуренты"     list={competitors} setList={setCompetitors} />
          <TagGroup label="Ниша"           list={niche}       setList={setNiche} />

          <div className={styles.section}>
            <div className={styles.sectionLabel}>🧬 ДНК бренда (сфера)</div>
            <textarea
              className={styles.nameInput}
              style={{ resize: 'vertical', minHeight: 48, fontFamily: 'var(--font-sans)' }}
              value={sphere}
              onChange={e => setSphere(e.target.value)}
              placeholder="Сфера бренда и интересы аудитории (определяется AI)"
            />
          </div>
          <div className={styles.section}>
            <div className={styles.sectionLabel}>📍 Город (локальный бизнес)</div>
            <input
              className={styles.nameInput}
              value={geo}
              onChange={e => setGeo(e.target.value)}
              placeholder="Напр. Москва — пусто для федерального бренда"
            />
          </div>
          {categoryTerms.length > 0 && (
            <TagGroup label="Категории конкурентов" list={categoryTerms} setList={setCategoryTerms} />
          )}
          <div className={styles.section}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, color: 'var(--fg-2)' }}>
              <input type="checkbox" checked={localMode} onChange={e => setLocalMode(e.target.checked)} />
              Локальный бизнес — широкая выдача по городу
            </label>
            <div style={{ fontSize: 11, color: 'var(--fg-4)' }}>
              Показывать весь городской контент аудитории (для салона — женский/лайфстайл). Авто для аккаунтов ≤1000 подписчиков с городом.
            </div>
          </div>
          {localMode && audienceTerms.length > 0 && (
            <TagGroup label="Темы аудитории" list={audienceTerms} setList={setAudienceTerms} />
          )}
          {voiceDescription && (
            <div className={styles.section}>
              <div className={styles.sectionLabel}>Голос бренда</div>
              <div style={{ fontSize: 13, color: 'var(--fg-2)' }}>{voiceDescription}</div>
            </div>
          )}
          {toneExamples.length > 0 && (
            <div className={styles.section}>
              <div className={styles.sectionLabel}>Примеры голоса</div>
              <div className={styles.tags}>
                {toneExamples.map((t, i) => (
                  <span key={i} className={styles.tag} style={{ maxWidth: '100%' }}>
                    {t.length > 60 ? t.slice(0, 60) + '…' : t}
                    <button className={styles.tagX}
                      onClick={() => setToneExamples(toneExamples.filter((_, j) => j !== i))}>✕</button>
                  </span>
                ))}
              </div>
            </div>
          )}
          <div style={{ fontSize: 12, color: 'var(--fg-4)' }}>
            Рынок: {market === 'ru' ? '🇷🇺 Русскоязычный / СНГ' : '🌍 Глобальный'}
          </div>
          {audience && (audience.positive + audience.negative + audience.neutral) > 0 && (
            <div style={{ fontSize: 12, color: 'var(--fg-4)' }}>
              Аудитория: {audience.positive} 👍 · {audience.negative} 👎 · {audience.neutral} 😐
            </div>
          )}

          <div className={styles.actions}>
            {mode === 'edit'
              ? <button className={styles.cancelBtn} onClick={onClose}>Отмена</button>
              : <button className={styles.cancelBtn} onClick={() => setStep(0)}>← К аккаунтам</button>}
            <button
              className={styles.nextBtn}
              onClick={handlePreview}
              disabled={previewing || keywords.length === 0}
            >
              {previewing ? <><span className={styles.spinner} />Загружаю…</> : 'Предпросмотр постов →'}
            </button>
          </div>
        </>
      )}

      {step === 2 && (
        <>
          {toast && <div className={styles.toast}>{toast}</div>}

          {previews.length > 0 ? (
            <div className={styles.previewList}>
              {previews.map((p, i) => (
                <div key={i} className={styles.previewCard}>
                  <div className={styles.previewMeta}>
                    <span className={styles.platformBadge}>{p.platform}</span>
                    <span>@{p.author}</span>
                    {p.views > 0 && <span>{(p.views / 1000).toFixed(1)}k просм.</span>}
                  </div>
                  <div className={styles.previewText}>{p.text}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className={styles.empty}>Превью недоступно — можно сохранить без него.</div>
          )}

          <div className={styles.actions}>
            <button className={styles.cancelBtn} onClick={() => setStep(1)}>← Назад</button>
            <button className={styles.nextBtn} onClick={handleSave} disabled={saving}>
              {saving
                ? <><span className={styles.spinner} />Сохраняю…</>
                : mode === 'create' ? 'Создать бренд' : 'Применить'}
            </button>
          </div>
        </>
      )}
    </>
  );

  if (mode === 'create') {
    return (
      <div className={styles.fullscreen}>
        <div className={styles.card}>{inner}</div>
      </div>
    );
  }

  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>{inner}</div>
    </div>
  );
}
