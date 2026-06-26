// Антиспам — управление фильтром мусора.
// Стоп-слова (быстрый слой, добавляются вручную) + примеры (копятся при скидывании
// постов из ленты, используются ИИ-слоем). Обе сущности живут в /intel/spam.
import { useEffect, useState } from 'react';
import { Icon } from '../../../core/components/icons';
import { intelApi } from '../api';
import styles from '../intel.module.css';

export function IntelSpam() {
  const [keywords, setKeywords] = useState([]);
  const [words, setWords]       = useState([]);
  const [examples, setExamples] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [newKeyword, setNewKeyword] = useState('');
  const [addingKw, setAddingKw] = useState(false);
  const [kwErr, setKwErr]       = useState('');
  const [newWord, setNewWord]   = useState('');
  const [adding, setAdding]     = useState(false);
  const [busy, setBusy]         = useState(null); // id being deleted
  const [err, setErr]           = useState('');

  async function load() {
    setLoading(true);
    try {
      const [k, w, e] = await Promise.all([
        intelApi.spamList('keyword'),
        intelApi.spamList('word'),
        intelApi.spamList('example'),
      ]);
      setKeywords(Array.isArray(k) ? k : []);
      setWords(Array.isArray(w) ? w : []);
      setExamples(Array.isArray(e) ? e : []);
    } catch {
      setKeywords([]); setWords([]); setExamples([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function handleAddKeyword(e) {
    e.preventDefault();
    // Разбиваем по запятым и переносам строк — можно скинуть пачку слов одним вводом,
    // каждое сохранится отдельной записью. Дубли (в т.ч. по регистру) отсекаем.
    const seen = new Set();
    const values = newKeyword
      .split(/[,\n;]+/)
      .map(v => v.trim())
      .filter(v => {
        if (!v) return false;
        const low = v.toLowerCase();
        if (seen.has(low)) return false;
        seen.add(low);
        return true;
      });
    if (values.length === 0) { setKwErr('Введите ключевое слово или фразу'); return; }
    setKwErr('');
    setAddingKw(true);
    try {
      const rows = await Promise.all(values.map(value => intelApi.addSpam({ kind: 'keyword', value })));
      setKeywords(prev => {
        const known = new Set(prev.map(k => k.id));
        const fresh = rows.filter(r => !known.has(r.id));
        return [...fresh, ...prev];
      });
      setNewKeyword('');
    } catch (ex) {
      setKwErr(ex.message || 'Ошибка добавления');
    } finally {
      setAddingKw(false);
    }
  }

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
      if (kind === 'keyword')   setKeywords(prev => prev.filter(k => k.id !== id));
      else if (kind === 'word') setWords(prev => prev.filter(w => w.id !== id));
      else                      setExamples(prev => prev.filter(e => e.id !== id));
    } catch (ex) {
      setErr(ex.message || 'Ошибка удаления');
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={styles.workspace}>
      {/* Ключевые слова — слой допуска (впускают пост в ленту) */}
      <div className={styles.section}>
        <div className={styles.srcHeader}>
          <span className={styles.sectionTitle}>
            <Icon name="search" size={13} color="#4FD08A" />
            Ключевые слова
            <span className={styles.sectionCount}>{keywords.length}</span>
          </span>
          <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 11, color: '#6A8499' }}>
            посты с этим словом попадают в ленту
          </span>
        </div>

        <form className={styles.srcAddForm} onSubmit={handleAddKeyword}>
          <input
            className={styles.srcInput}
            placeholder="слова через запятую — каждое сохранится отдельно"
            value={newKeyword}
            onChange={e => { setNewKeyword(e.target.value); setKwErr(''); }}
            disabled={addingKw}
          />
          <button type="submit" className={styles.srcAddBtn} disabled={addingKw}>
            {addingKw ? '…' : '+ Добавить'}
          </button>
          {kwErr && <span className={styles.srcError}>{kwErr}</span>}
        </form>

        <div className={styles.sectionBody}>
          {loading ? (
            <div className={styles.empty}>Загрузка…</div>
          ) : keywords.length === 0 ? (
            <div className={styles.empty}>Ключевых слов пока нет.</div>
          ) : (
            keywords.map(k => (
              <div key={k.id} className={styles.srcRow}>
                <span className={styles.srcHandle}>{k.value}</span>
                <button
                  className={styles.srcDel}
                  onClick={() => handleDelete(k.id, 'keyword')}
                  disabled={busy === k.id}
                  title="Удалить"
                >✕</button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Стоп-слова */}
      <div className={styles.section} style={{ marginTop: 16 }}>
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
