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

export const postAction = (mentionId, action, draft = null) =>
  request(`/mentions/${mentionId}/action`, {
    method: 'POST',
    body: JSON.stringify({ action, draft }),
  });
