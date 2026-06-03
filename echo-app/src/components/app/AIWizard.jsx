import { useState } from 'react';
import * as api from '../../services/api';
import styles from './aiwizard.module.css';

/**
 * AIWizard — 2-step brand setup wizard.
 * mode="create" → fullscreen onboarding, calls POST /onboarding
 * mode="edit"   → modal overlay, calls POST /brands/:id/config
 */
export function AIWizard({ mode, brand, onSaved, onClose }) {
  const [step, setStep]             = useState(1);
  const [name, setName]             = useState(brand?.name ?? '');
  const [keywords, setKeywords]     = useState(brand?.keywords ?? []);
  const [hashtags, setHashtags]     = useState(brand?.hashtags ?? []);
  const [competitors, setCompetitors] = useState(brand?.competitors ?? []);
  const [niche, setNiche]           = useState(brand?.niche_keywords ?? []);
  const [previews, setPreviews]     = useState([]);
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
      if (!data.keywords?.length && !data.competitors?.length) {
        showToast('AI не смог подобрать автоматически — заполните вручную.');
      }
    } catch {
      showToast('AI недоступен — заполните поля вручную и нажмите «Далее».');
    } finally {
      setSuggesting(false);
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
        result = await api.createBrand(name.trim(), keywords, hashtags, competitors, niche);
        api.collectBrand(result.id).catch(() => {});
      } else {
        await api.updateBrandConfig(brand.id, {
          name: name.trim(), keywords, hashtags,
          exclusions: brand.exclusions ?? [],
          competitors, niche_keywords: niche,
        });
        result = { ...brand, name: name.trim(), keywords, hashtags, competitors, niche_keywords: niche };
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
          {step === 1
            ? 'Введите название бренда — AI подберёт ключевые слова, конкурентов и нишу'
            : 'Реальные посты по вашим ключевым словам'}
        </div>
      </div>

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

          <div className={styles.actions}>
            {mode === 'edit' && (
              <button className={styles.cancelBtn} onClick={onClose}>Отмена</button>
            )}
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
