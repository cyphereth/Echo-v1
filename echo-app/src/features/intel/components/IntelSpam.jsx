// Антиспам — управление фильтром мусора.
// Стоп-слова (быстрый слой, добавляются вручную) + примеры (копятся при скидывании
// постов из ленты, используются ИИ-слоем). Обе сущности живут в /intel/spam.
import { useEffect, useState } from 'react';
import { Icon } from '../../../core/components/icons';
import { intelApi } from '../api';
import styles from '../intel.module.css';

export function IntelSpam() {
  const [words, setWords]       = useState([]);
  const [examples, setExamples] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [newWord, setNewWord]   = useState('');
  const [adding, setAdding]     = useState(false);
  const [busy, setBusy]         = useState(null); // id being deleted
  const [err, setErr]           = useState('');

  async function load() {
    setLoading(true);
    try {
      const [w, e] = await Promise.all([intelApi.spamList('word'), intelApi.spamList('example')]);
      setWords(Array.isArray(w) ? w : []);
      setExamples(Array.isArray(e) ? e : []);
    } catch {
      setWords([]); setExamples([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function handleAddWord(e) {
    e.preventDefault();
    const value = newWord.trim();
    if (!value) { setErr('Введите стоп-слово или фразу'); return; }
    setErr('');
    setAdding(true);
    try {
      const row = await intelApi.addSpam({ kind: 'word', value });
      setWords(prev => prev.some(w => w.id === row.id) ? prev : [row, ...prev]);
      setNewWord('');
    } catch (ex) {
      setErr(ex.message || 'Ошибка добавления');
    } finally {
      setAdding(false);
    }
  }

  async function handleDelete(id, kind) {
    if (busy) return;
    setBusy(id);
    try {
      await intelApi.deleteSpam(id);
      if (kind === 'word') setWords(prev => prev.filter(w => w.id !== id));
      else setExamples(prev => prev.filter(e => e.id !== id));
    } catch (ex) {
      setErr(ex.message || 'Ошибка удаления');
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={styles.workspace}>
      {/* Стоп-слова */}
      <div className={styles.section}>
        <div className={styles.srcHeader}>
          <span className={styles.sectionTitle}>
            <Icon name="search" size={13} color="#FF7A87" />
            Стоп-слова
            <span className={styles.sectionCount}>{words.length}</span>
          </span>
        </div>

        <form className={styles.srcAddForm} onSubmit={handleAddWord}>
          <input
            className={styles.srcInput}
            placeholder="слово или фраза — посты с ним отсекаются сразу"
            value={newWord}
            onChange={e => { setNewWord(e.target.value); setErr(''); }}
            disabled={adding}
          />
          <button type="submit" className={styles.srcAddBtn} disabled={adding}>
            {adding ? '…' : '+ Добавить'}
          </button>
          {err && <span className={styles.srcError}>{err}</span>}
        </form>

        <div className={styles.sectionBody}>
          {loading ? (
            <div className={styles.empty}>Загрузка…</div>
          ) : words.length === 0 ? (
            <div className={styles.empty}>Стоп-слов пока нет.</div>
          ) : (
            words.map(w => (
              <div key={w.id} className={styles.srcRow}>
                <span className={styles.srcHandle}>{w.value}</span>
                <button
                  className={styles.srcDel}
                  onClick={() => handleDelete(w.id, 'word')}
                  disabled={busy === w.id}
                  title="Удалить"
                >✕</button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Примеры мусора */}
      <div className={styles.section} style={{ marginTop: 16 }}>
        <div className={styles.srcHeader}>
          <span className={styles.sectionTitle}>
            <Icon name="activity" size={13} color="#57D2E2" />
            Примеры мусора
            <span className={styles.sectionCount}>{examples.length}</span>
          </span>
          <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 11, color: '#6A8499' }}>
            скидываются из ленты · эталон для ИИ-фильтра
          </span>
        </div>

        <div className={styles.sectionBody}>
          {loading ? (
            <div className={styles.empty}>Загрузка…</div>
          ) : examples.length === 0 ? (
            <div className={styles.empty}>Примеров пока нет. Жмите ✕ на посте в ленте, чтобы добавить.</div>
          ) : (
            examples.map(ex => (
              <div key={ex.id} className={styles.eventRow}>
                <div className={styles.eventBody}>
                  <div className={styles.eventText}>{ex.value}</div>
                  {ex.author && <div className={styles.eventMeta}>{ex.author}</div>}
                </div>
                <button
                  className={styles.eventSpam}
                  style={{ opacity: 1 }}
                  onClick={() => handleDelete(ex.id, 'example')}
                  disabled={busy === ex.id}
                  title="Удалить пример"
                >✕</button>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
