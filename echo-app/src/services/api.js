async function request(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status}: ${text.slice(0, 200)}`);
  }
  return res.json();
}

export const getBrands       = ()            => request('/brands');
export const getBrand        = (id)          => request(`/brands/${id}`);
export const getInbox        = (brandId)     => request(`/inbox?brand_id=${brandId}`);
export const collectBrand    = (brandId)     => request(`/brands/${brandId}/collect`, { method: 'POST' });
export const searchMentions  = (q)           => request(`/search?query=${encodeURIComponent(q)}`);

export const createBrand = (name, keywords = [], hashtags = []) =>
  request('/onboarding', {
    method: 'POST',
    body: JSON.stringify({ name, keywords, hashtags }),
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

export const getComments = (mentionId, refresh = false) =>
  request(`/mentions/${mentionId}/comments${refresh ? '?refresh=1' : ''}`);

export const commentAction = (commentId, action, draft = null) =>
  request(`/comments/${commentId}/action`, {
    method: 'POST',
    body: JSON.stringify({ action, draft }),
  });

export const regenerateComment = (commentId) =>
  request(`/comments/${commentId}/regenerate`, { method: 'POST' });
