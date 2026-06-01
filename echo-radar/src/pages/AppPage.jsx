import { useState, useEffect } from 'react';
import { Icon } from '../components/shared/icons';
import { Eyebrow } from '../components/shared/primitives';
import { Sidebar, TopBar } from '../components/app/Shell';
import { Inbox } from '../components/app/Inbox';
import { DetailPanel } from '../components/app/Detail';
import { ProbesScreen } from '../components/app/Probes';
import { useBrands } from '../hooks/useBrands';
import { useInbox } from '../hooks/useInbox';
import styles from '../components/app/app.module.css';

// ── Scope bar ─────────────────────────────────────────────────────────────────

function ScopeBar({ data, lastSync }) {
  const live = data.filter(m => m.status === 'new').length;
  const crit = data.filter(m => m.severity >= 75 && m.status === 'new').length;
  const rise = data.filter(m => m.severity >= 45 && m.severity < 75 && m.status === 'new').length;

  function syncLabel() {
    if (!lastSync) return 'синхронизируется…';
    const s = Math.floor((Date.now() - lastSync.getTime()) / 1000);
    if (s < 5)  return 'только что';
    if (s < 60) return `${s} сек назад`;
    return `${Math.floor(s / 60)} мин назад`;
  }

  const Stat = ({ label, value, color }) => (
    <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 7 }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 16, color,
        fontVariantNumeric: 'tabular-nums' }}>{value}</span>
      <Eyebrow>{label}</Eyebrow>
    </span>
  );
  return (
    <div className={styles.scope}>
      <span className={styles.scopeLive}><span className={styles.pulse} />В эфире</span>
      <span style={{ width: 1, height: 18, background: 'var(--line-2)' }} />
      <Stat label="сигналов" value={live} color="var(--fg-1)" />
      <Stat label="залетает" value={crit} color="#FF7A87" />
      <Stat label="растёт"   value={rise} color="#FFC871" />
      <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--fg-3)' }}>
        синхронизация {syncLabel()}
      </span>
    </div>
  );
}

// ── Loading / Error states ────────────────────────────────────────────────────

function Spinner() {
  return (
    <div style={{ flex: 1, display: 'grid', placeItems: 'center', color: 'var(--fg-3)',
      fontFamily: 'var(--font-mono)', fontSize: 13 }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
        <span style={{ width: 9, height: 9, borderRadius: 999, background: 'var(--brand)',
          animation: 'pulse 1.4s ease-in-out infinite' }} />
        Загружаем инбокс…
      </div>
    </div>
  );
}

function ErrorBanner({ message, onRetry }) {
  return (
    <div style={{ flex: 1, display: 'grid', placeItems: 'center' }}>
      <div style={{ background: 'var(--sev-critical-ghost)', border: '1px solid var(--sev-critical-line)',
        borderRadius: 'var(--r-lg)', padding: '20px 28px', maxWidth: 440, textAlign: 'center' }}>
        <Icon name="activity" size={20} color="var(--sev-critical)" style={{ marginBottom: 10 }} />
        <div style={{ fontWeight: 700, color: 'var(--fg-1)', marginBottom: 6 }}>
          Нет связи с бэкендом
        </div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--fg-3)', marginBottom: 16 }}>
          {message}
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--fg-2)', lineHeight: 1.6, marginBottom: 16 }}>
          Запустите бэкенд:<br />
          <code style={{ background: 'var(--surface-2)', padding: '2px 6px', borderRadius: 4,
            fontFamily: 'var(--font-mono)', fontSize: 12 }}>
            uvicorn radar.api:app --reload
          </code>
        </div>
        <button onClick={onRetry} style={{ background: 'var(--surface-2)', border: '1px solid var(--line-strong)',
          borderRadius: 'var(--r-md)', padding: '8px 18px', color: 'var(--fg-1)', fontWeight: 600,
          fontSize: 13, cursor: 'pointer' }}>Повторить</button>
      </div>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function NoBrands() {
  return (
    <div style={{ flex: 1, display: 'grid', placeItems: 'center' }}>
      <div style={{ textAlign: 'center', maxWidth: 380 }}>
        <Icon name="radio" size={32} color="var(--brand)" style={{ marginBottom: 14 }} />
        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--fg-1)', marginBottom: 8 }}>
          Брендов пока нет
        </div>
        <div style={{ fontSize: 14, color: 'var(--fg-2)', lineHeight: 1.6, marginBottom: 20 }}>
          Создайте первый бренд через экран настройки
        </div>
        <a href="/setup" style={{ display: 'inline-flex', alignItems: 'center', gap: 8,
          background: 'var(--brand)', color: 'var(--fg-on-brand)', borderRadius: 'var(--r-md)',
          padding: '10px 20px', fontWeight: 700, fontSize: 14, textDecoration: 'none' }}>
          <Icon name="plus" size={16} />Настроить бренд
        </a>
      </div>
    </div>
  );
}

// ── App shell ─────────────────────────────────────────────────────────────────

export default function AppPage() {
  const [screen, setScreen]   = useState('inbox');
  const [selectedId, setSelectedId] = useState(null);
  const [toast, setToast]     = useState(null);
  const [brandIdx, setBrandIdx] = useState(0);

  const { brands, loading: brandsLoading, error: brandsError } = useBrands();
  const brand   = brands[brandIdx] ?? null;
  const brandId = brand?.id ?? null;

  const { mentions, loading, error, lastSync, doAction } = useInbox(brandId);

  // auto-select first mention when inbox loads
  useEffect(() => {
    if (!selectedId && mentions.length > 0) setSelectedId(String(mentions[0].id));
  }, [mentions, selectedId]);

  const visible  = mentions.filter(m => m.status !== 'rejected');
  const selected = visible.find(m => m.id === String(selectedId));
  const prCount  = mentions.filter(m => (m.lane === 'PR' || m.lane === 'none') && m.status === 'new').length;

  function flash(msg) {
    setToast(msg);
    clearTimeout(window.__erT);
    window.__erT = setTimeout(() => setToast(null), 2600);
  }

  async function onAction(id, action, editedDraft = null) {
    try {
      await doAction(id, action, editedDraft);
      if (action === 'approve') flash('Ответ отправлен · правка залогирована для tone-learning');
      if (action === 'reject')  { flash('Отклонено как шум'); const next = visible.find(m => m.id !== id); if (next) setSelectedId(next.id); }
      if (action === 'pr')      flash('Передано в PR — срочно');
    } catch {
      flash('Ошибка — проверьте соединение с бэкендом');
    }
  }

  // Brand object adapted for Shell component
  const brandForShell = brand
    ? { name: brand.name, handle: `@${brand.name.toLowerCase().replace(/\s+/g, '')}`, monogram: brand.name.slice(0, 2).toUpperCase(), probes: brand.probes?.length ?? 0 }
    : { name: '—', handle: '', monogram: '??', probes: 0 };

  return (
    <div className={styles.app} style={{ color: 'var(--fg-2)', fontFamily: 'var(--font-sans)', background: 'var(--bg-void)' }}>
      <Sidebar screen={screen} setScreen={setScreen} prCount={prCount} brand={brandForShell} />

      <div className={styles.main}>
        <TopBar
          title={screen === 'inbox' ? 'Инбокс' : 'Зонды'}
          sub={screen === 'inbox' ? 'две полосы · PR и SMM' : 'ключевые слова и хэштеги'}
          brand={brandForShell}
          brands={brands}
          onBrandChange={setBrandIdx}
        />

        {screen === 'inbox' ? (
          brandsLoading ? <Spinner /> :
          brandsError   ? <ErrorBanner message={brandsError} onRetry={() => window.location.reload()} /> :
          brands.length === 0 ? <NoBrands /> :
          <>
            <ScopeBar data={mentions} lastSync={lastSync} />
            <div className={styles.workspace}>
              {loading && mentions.length === 0
                ? <Spinner />
                : error && mentions.length === 0
                  ? <ErrorBanner message={error} onRetry={() => window.location.reload()} />
                  : <Inbox data={visible} selectedId={selectedId} onSelect={setSelectedId} />}
              {selected
                ? <DetailPanel m={selected} onAction={onAction} />
                : <aside className={styles.detail}><div className={styles.empty} style={{ margin: 'auto' }}>Выберите упоминание</div></aside>}
            </div>
          </>
        ) : (
          <ProbesScreen brandId={brandId} brandName={brand?.name} />
        )}
      </div>

      {toast && <div className={styles.toast}><Icon name="check" size={15} color="var(--sev-calm)" />{toast}</div>}
    </div>
  );
}
