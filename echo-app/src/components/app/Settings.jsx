import { useState, useEffect } from 'react';
import { Icon } from '../shared/icons';
import * as api from '../../services/api';
import styles from './settings.module.css';

// ── Tag input component ──────────────────────────────────────────────────────

function TagInput({ tags, onChange, placeholder, color = 'var(--brand)', prefix = '' }) {
  const [val, setVal] = useState('');

  function add() {
    const trimmed = val.trim().replace(/^#+/, '');
    if (!trimmed) return;
    const tag = prefix + trimmed;
    if (!tags.includes(tag)) onChange([...tags, tag]);
    setVal('');
  }

  function remove(t) { onChange(tags.filter(x => x !== t)); }

  return (
    <div>
      <div className={styles.tagInputWrap}>
        <input
          className={styles.tagInput}
          value={val}
          onChange={e => setVal(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); add(); } }}
          placeholder={placeholder}
        />
        <button className={styles.addBtn} onClick={add}>
          <Icon name="plus" size={13} />Добавить
        </button>
      </div>
      <div className={styles.tags}>
        {tags.length === 0
          ? <span className={styles.emptyTags}>Пока пусто — добавьте первый</span>
          : tags.map(t => (
            <span key={t} className={styles.tag} style={{
              background: color + '18',
              color,
              border: `1px solid ${color}33`,
            }}>
              {t}
              <button className={styles.tagX} onClick={() => remove(t)}>
                <Icon name="x" size={10} color={color} />
              </button>
            </span>
          ))}
      </div>
    </div>
  );
}

// ── Platform toggle ──────────────────────────────────────────────────────────

function PlatformToggle({ name, icon, note, on, onToggle }) {
  return (
    <div className={styles.platformRow} data-on={on ? '1' : '0'} onClick={onToggle}>
      <Icon name={icon} size={22} />
      <div className={styles.platformInfo}>
        <div className={styles.platformName}>{name}</div>
        <div className={styles.platformNote}>{note}</div>
      </div>
      <button className={styles.toggle} data-on={on ? '1' : '0'}>
        <div className={styles.toggleKnob} />
      </button>
    </div>
  );
}

// ── Section wrapper ──────────────────────────────────────────────────────────

function Section({ title, sub, children }) {
  return (
    <div className={styles.section}>
      <div className={styles.sectionHead}>
        <div className={styles.sectionTitle}>{title}</div>
        {sub && <div className={styles.sectionSub}>{sub}</div>}
      </div>
      {children}
    </div>
  );
}

// ── Nav items ────────────────────────────────────────────────────────────────

const NAV = [
  { key: 'brand',       label: 'Бренд',            icon: 'building' },
  { key: 'keywords',    label: 'Ключевые слова',    icon: 'search' },
  { key: 'competitors', label: 'Конкуренты',        icon: 'users' },
  { key: 'platforms',   label: 'Платформы',         icon: 'radio' },
  { key: 'voice',       label: 'Голос бренда',      icon: 'messageCircle' },
];

const VOICE_PRESETS = [
  { key: 'friendly',   title: 'Дружелюбный',  desc: 'Тепло, по-человечески, с эмодзи. Подходит для кафе, магазинов.' },
  { key: 'formal',     title: 'Официальный',  desc: 'Уважительно и строго. Подходит для банков, клиник, юридических компаний.' },
  { key: 'expert',     title: 'Экспертный',   desc: 'Спокойно и уверенно. Показываем знания, без лишнего пафоса.' },
];

// ── Save bar ─────────────────────────────────────────────────────────────────

function SaveBar({ onSave, onCollect, saved, saving, collecting, showCollect }) {
  return (
    <div className={styles.saveBar}>
      {showCollect && (
        <button
          className={styles.collectBtn}
          onClick={onCollect}
          disabled={collecting}
        >
          {collecting ? '⏳ Сбор…' : '⚡ Собрать данные'}
        </button>
      )}
      <button className={styles.saveBtn} onClick={onSave} disabled={saving}>
        <Icon name={saved ? 'check' : 'checkCircle'} size={15} />
        {saved ? 'Сохранено!' : saving ? 'Сохранение…' : 'Сохранить'}
      </button>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

export function SettingsScreen({ brand, onBrandSaved, onCollect, collecting }) {
  const [tab, setTab] = useState('brand');

  // Brand fields
  const [brandName,      setBrandName]      = useState('PapaPizza');
  const [brandNiche,     setBrandNiche]     = useState('Доставка еды, пиццерия');
  const [brandInstagram, setBrandInstagram] = useState('@papapizza_ru');
  const [brandTiktok,    setBrandTiktok]    = useState('@papapizza');
  const [brandWebsite,   setBrandWebsite]   = useState('papapizza.ru');

  // Keywords
  const [keywords,   setKeywords]   = useState(['папапицца', 'papapizza', 'papa pizza', 'пицца доставка мск']);
  const [hashtags,   setHashtags]   = useState(['#папапицца', '#papapizza', '#пиццамосква']);
  const [exclusions, setExclusions] = useState(['домино', 'додо', 'рецепт пицца']);

  // Competitors
  const [competitors, setCompetitors] = useState(['DoDo Pizza', 'Dominos', 'Pizza Hut']);

  // Platforms
  const [platforms, setPlatforms] = useState({ instagram: true, tiktok: true, telegram: false });
  function togglePlatform(p) { setPlatforms(prev => ({ ...prev, [p]: !prev[p] })); }

  // Voice
  const [voice, setVoice] = useState('friendly');
  const [toneExample, setToneExample] = useState('Привет! Очень жаль, что так вышло. Напишите нам в директ — разберёмся и всё исправим 🙏');

  const [saved,  setSaved]  = useState(false);
  const [saving, setSaving] = useState(false);

  // Sync from brand prop when it loads
  useEffect(() => {
    if (!brand) return;
    setBrandName(brand.name ?? '');
    if (brand.keywords?.length) setKeywords(brand.keywords);
    if (brand.hashtags?.length)  setHashtags(brand.hashtags);
  }, [brand?.id]);

  async function save() {
    setSaving(true);
    try {
      let result;
      if (!brand) {
        result = await api.createBrand(brandName, keywords, hashtags);
      } else {
        result = await api.updateBrandConfig(brand.id, { keywords, hashtags, exclusions });
        result = { ...brand, ...result };
      }
      onBrandSaved?.(result);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      console.error('Save failed:', e.message);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  const saveBar = (showCollect = false) => (
    <SaveBar
      onSave={save}
      onCollect={onCollect}
      saved={saved}
      saving={saving}
      collecting={collecting}
      showCollect={showCollect && !!brand}
    />
  );

  return (
    <div className={styles.page}>
      {/* Side nav */}
      <nav className={styles.sidenav}>
        {NAV.map(n => (
          <button key={n.key} className={styles.sidenavItem}
            data-active={tab === n.key ? '1' : '0'}
            onClick={() => setTab(n.key)}>
            <Icon name={n.icon} size={15} />
            {n.label}
          </button>
        ))}
      </nav>

      {/* Content */}
      <div className={styles.content}>

        {tab === 'brand' && (
          <>
            <Section title="Профиль бренда" sub="Основная информация о компании. Используется для контекста при генерации ответов.">
              <div className={styles.field}>
                <label className={styles.label}>Название бренда</label>
                <input className={styles.input} value={brandName}
                  onChange={e => setBrandName(e.target.value)} placeholder="Например: PapaPizza" />
              </div>
              <div className={styles.field}>
                <label className={styles.label}>Ниша / описание</label>
                <input className={styles.input} value={brandNiche}
                  onChange={e => setBrandNiche(e.target.value)} placeholder="Например: доставка еды, пиццерия" />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div className={styles.field} style={{ marginBottom: 0 }}>
                  <label className={styles.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Icon name="instagram" size={13} />Instagram
                  </label>
                  <input className={styles.input} value={brandInstagram}
                    onChange={e => setBrandInstagram(e.target.value)} placeholder="@аккаунт" />
                </div>
                <div className={styles.field} style={{ marginBottom: 0 }}>
                  <label className={styles.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Icon name="tiktok" size={13} />TikTok
                  </label>
                  <input className={styles.input} value={brandTiktok}
                    onChange={e => setBrandTiktok(e.target.value)} placeholder="@аккаунт" />
                </div>
              </div>
              <div className={styles.field}>
                <label className={styles.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Icon name="externalLink" size={13} />Сайт
                </label>
                <input className={styles.input} value={brandWebsite}
                  onChange={e => setBrandWebsite(e.target.value)} placeholder="example.ru" />
              </div>
            </Section>

            {!brand && (
              <div style={{ padding: '12px 16px', background: 'var(--brand-dim)', border: '1px solid rgba(78,110,242,0.3)', borderRadius: 'var(--r-lg)', fontSize: 13, color: 'var(--brand-bright)' }}>
                💡 Сохраните профиль, чтобы начать сбор упоминаний
              </div>
            )}

            {saveBar(false)}
          </>
        )}

        {tab === 'keywords' && (
          <>
            <Section
              title="Ключевые слова"
              sub="Echo будет искать посты и комментарии, содержащие эти слова. Добавьте названия бренда, продуктов, слоганы — всё что люди могут написать о вас.">
              <TagInput
                tags={keywords}
                onChange={setKeywords}
                placeholder="Введите слово или фразу, нажмите Enter"
                color="var(--brand-bright)"
              />
            </Section>

            <Section
              title="Хэштеги"
              sub="Поиск по хэштегам в Instagram и TikTok. Вводите без # — добавим автоматически.">
              <TagInput
                tags={hashtags}
                onChange={setHashtags}
                placeholder="пицца, доставкаеды..."
                color="var(--ig)"
                prefix="#"
              />
            </Section>

            <Section
              title="Исключения"
              sub="Слова-фильтры — посты с этими словами не попадут в ленту. Удобно чтобы отсечь нерелевантные упоминания и рецепты.">
              <TagInput
                tags={exclusions}
                onChange={setExclusions}
                placeholder="рецепт, сделай сам..."
                color="var(--neg)"
              />
            </Section>

            <div style={{ background: 'var(--surface-2)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-lg)', padding: '14px 18px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <Icon name="sparkles" size={14} color="var(--brand-bright)" />
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-1)' }}>Подсказка AI</span>
              </div>
              <p style={{ fontSize: 12.5, color: 'var(--fg-3)', lineHeight: 1.6 }}>
                Не знаете с чего начать? Введите ссылку на ваш сайт или аккаунт — Echo предложит ключевые слова автоматически.
              </p>
              <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                <input className={styles.input} style={{ flex: 1, fontFamily: 'var(--font-mono)', fontSize: 13 }}
                  placeholder="https://papapizza.ru или @papapizza_ru" />
                <button className={styles.addBtn}>
                  <Icon name="sparkles" size={13} />Разобрать
                </button>
              </div>
            </div>

            {saveBar(true)}
          </>
        )}

        {tab === 'competitors' && (
          <>
            <Section
              title="Конкуренты"
              sub="Echo будет искать негативные упоминания этих брендов — отличная возможность перехватить недовольную аудиторию конкурентов.">
              <TagInput
                tags={competitors}
                onChange={setCompetitors}
                placeholder="Название конкурента, нажмите Enter"
                color="var(--lane-competitor)"
              />
              {competitors.length > 0 && (
                <div style={{ marginTop: 16, padding: '12px 14px', background: 'var(--surface-2)', borderRadius: 'var(--r-md)', fontSize: 12.5, color: 'var(--fg-3)', lineHeight: 1.6 }}>
                  💡 Echo ищет негативные посты о <strong style={{ color: 'var(--fg-2)' }}>{competitors.join(', ')}</strong> и выводит их в ленту «Конкуренты». Вы можете ответить на комментарии аудитории и предложить свой продукт как альтернативу.
                </div>
              )}
            </Section>
            {saveBar(false)}
          </>
        )}

        {tab === 'platforms' && (
          <>
            <Section title="Платформы" sub="Выберите где Echo будет мониторить упоминания. Можно подключить несколько.">
              <div className={styles.platforms}>
                <PlatformToggle name="Instagram" icon="instagram" note="Reels, посты, комментарии"
                  on={platforms.instagram} onToggle={() => togglePlatform('instagram')} />
                <PlatformToggle name="TikTok" icon="tiktok" note="Видео и комментарии"
                  on={platforms.tiktok} onToggle={() => togglePlatform('tiktok')} />
                <PlatformToggle name="Telegram" icon="telegram" note="Каналы и публичные чаты"
                  on={platforms.telegram} onToggle={() => togglePlatform('telegram')} />
              </div>
            </Section>
            {saveBar(false)}
          </>
        )}

        {tab === 'voice' && (
          <>
            <Section title="Голос бренда" sub="Как звучат ответы от вашего имени. AI учитывает это при генерации черновиков.">
              <div className={styles.voicePresets}>
                {VOICE_PRESETS.map(p => (
                  <button key={p.key} className={styles.voiceCard}
                    data-active={voice === p.key ? '1' : '0'}
                    onClick={() => setVoice(p.key)}>
                    <div className={styles.voiceCardTitle}>{p.title}</div>
                    <div className={styles.voiceCardDesc}>{p.desc}</div>
                  </button>
                ))}
              </div>
            </Section>

            <Section title="Пример голоса" sub="Напишите как ваш бренд отвечает на негативный комментарий. AI запомнит стиль.">
              <div className={styles.field}>
                <label className={styles.label}>Пример ответа на негатив</label>
                <textarea className={styles.textarea} value={toneExample}
                  onChange={e => setToneExample(e.target.value)}
                  placeholder="Напишите как вы обычно отвечаете на жалобы..." />
              </div>
              <div style={{ marginTop: 4, padding: '10px 14px', background: 'var(--surface-2)', borderRadius: 'var(--r-md)' }}>
                <div style={{ fontSize: 11, color: 'var(--fg-4)', fontFamily: 'var(--font-mono)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.07em' }}>Превью</div>
                <p style={{ fontSize: 13, color: 'var(--fg-2)', lineHeight: 1.6, fontStyle: 'italic' }}>
                  «{toneExample || 'Введите пример выше'}»
                </p>
              </div>
            </Section>

            {saveBar(false)}
          </>
        )}

      </div>
    </div>
  );
}
