const TOKEN_KEY = 'echo_token';
export const getToken   = () => localStorage.getItem(TOKEN_KEY);
export const setToken   = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

async function request(path, opts = {}) {
  const token = getToken();
  const res = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...opts.headers,
    },
    ...opts,
  });
  if (res.status === 401 && !path.startsWith('/auth')) {
    clearToken();
    if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
      window.location.assign('/login');
    }
    throw new Error('401: unauthorized');
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status}: ${text.slice(0, 200)}`);
  }
  return res.json();
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export const register = (email, password) =>
  request('/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) });
export const login = (email, password) =>
  request('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
export const me = () => request('/auth/me');
export const logout = () => clearToken();

export const getBrands       = ()            => request('/brands');
export const getBrand        = (id)          => request(`/brands/${id}`);
export const getInbox        = (brandId)     => request(`/inbox?brand_id=${brandId}`);
export const collectBrand    = (brandId)     => request(`/brands/${brandId}/collect`, { method: 'POST' });
export const searchMentions  = (q)           => request(`/search?query=${encodeURIComponent(q)}`);

export const createBrand = (name, keywords = [], hashtags = [], competitors = [], niche_keywords = [], tone_examples = [], market = 'global') =>
  request('/onboarding', {
    method: 'POST',
    body: JSON.stringify({ name, keywords, hashtags, competitors, niche_keywords, tone_examples, market }),
  });

export const scanProfile = (tiktok, instagram) =>
  request('/brands/profile-scan', {
    method: 'POST',
    body: JSON.stringify({ tiktok, instagram }),
  });

export const updateBrandConfig = (brandId, config) =>
  request(`/brands/${brandId}/config`, {
    method: 'POST',
    body: JSON.stringify(config),
  });

export const setAutoCollect = (brandId, enabled) =>
  request(`/brands/${brandId}/autocollect`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  });

export const postAction = (mentionId, action, draft = null) =>
  request(`/mentions/${mentionId}/action`, {
    method: 'POST',
    body: JSON.stringify({ action, draft }),
  });

export const getMention      = (mentionId) => request(`/mentions/${mentionId}`);
export const regenerateDraft = (mentionId) =>
  request(`/mentions/${mentionId}/regenerate`, { method: 'POST' });

export const getAnalytics = (brandId) => request(`/analytics?brand_id=${brandId}`);

export const getOpportunities = (brandId) => request(`/opportunities?brand_id=${brandId}`);

export const getComments = (mentionId, refresh = false) =>
  request(`/mentions/${mentionId}/comments${refresh ? '?refresh=1' : ''}`);

export const commentAction = (commentId, action, draft = null) =>
  request(`/comments/${commentId}/action`, {
    method: 'POST',
    body: JSON.stringify({ action, draft }),
  });

export const regenerateComment = (commentId) =>
  request(`/comments/${commentId}/regenerate`, { method: 'POST' });

export const suggestBrand = (name) =>
  request('/brands/suggest', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });

export const previewBrand = (keywords, platforms = ['tiktok', 'instagram']) =>
  request('/brands/preview', {
    method: 'POST',
    body: JSON.stringify({ keywords, platforms }),
  });
