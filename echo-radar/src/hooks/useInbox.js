import { useState, useEffect, useCallback, useRef } from 'react';
import { getInbox, postAction, normalizeMention } from '../services/api';

const POLL_MS = 30_000; // опрос каждые 30 сек

export function useInbox(brandId) {
  const [mentions, setMentions] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);
  const [lastSync, setLastSync] = useState(null);
  const timerRef = useRef(null);

  const fetch = useCallback(async () => {
    if (!brandId) return;
    try {
      const data = await getInbox(brandId);
      // API returns { pr: [...], smm: [...] } or flat array
      const raw = Array.isArray(data) ? data : [...(data.pr ?? []), ...(data.smm ?? [])];
      setMentions(prev => {
        const normalized = raw.map(normalizeMention);
        // preserve local status overrides (approve/reject done in UI)
        const statusMap = Object.fromEntries(prev.map(m => [m.id, m.status]));
        return normalized.map(m => ({ ...m, status: statusMap[m.id] ?? m.status }));
      });
      setLastSync(new Date());
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [brandId]);

  useEffect(() => {
    setLoading(true);
    fetch();
    timerRef.current = setInterval(fetch, POLL_MS);
    return () => clearInterval(timerRef.current);
  }, [fetch]);

  // Optimistic local action + POST to backend
  const doAction = useCallback(async (id, action, editedDraft = null) => {
    // optimistic update
    setMentions(prev => prev.map(m => {
      if (m.id !== id) return m;
      if (action === 'approve') return { ...m, status: 'sent', draft: editedDraft ?? m.draft };
      if (action === 'reject')  return { ...m, status: 'rejected' };
      if (action === 'pr')      return { ...m, lane: 'PR', status: 'new', humor: false };
      return m;
    }));
    try {
      await postAction(id, action, editedDraft);
    } catch (e) {
      // revert on error
      fetch();
      throw e;
    }
  }, [fetch]);

  return { mentions, loading, error, lastSync, doAction };
}
