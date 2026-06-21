// Brand-domain API functions — wired to brand backend endpoints.
// No scope helpers: all functions take brandId explicitly.
import { request } from '../../core/api/client';

// ── Auth helpers (re-exported for brand components) ───────────────────────────
export { clearToken } from '../../core/api/client';

// ── Brands ────────────────────────────────────────────────────────────────────
export const getBrands       = ()           => request('/brands');
export const getBrand        = (id)         => request(`/brands/${id}`);
export const collectBrand    = (brandId)    => request(`/brands/${brandId}/collect`, { method: 'POST' });
export const setAutoCollect  = (brandId, enabled) =>
  request(`/brands/${brandId}/autocollect`, { method: 'POST', body: JSON.stringify({ enabled }) });
export const updateBrandConfig = (brandId, config) =>
  request(`/brands/${brandId}/config`, { method: 'POST', body: JSON.stringify(config) });

// ── Onboarding / create brand ─────────────────────────────────────────────────
export const createBrand = (
  name, keywords = [], hashtags = [], competitors = [],
  niche_keywords = [], tone_examples = [], market = 'global',
  sphere = '', geo = '', category_terms = [], audience_terms = [],
  followers = 0, local_mode = false,
) =>
  request('/onboarding', {
    method: 'POST',
    body: JSON.stringify({
      name, keywords, hashtags, competitors, niche_keywords, tone_examples,
      market, sphere, geo, category_terms, audience_terms, followers, local_mode,
    }),
  });

// ── AI brand suggest / scan ───────────────────────────────────────────────────
export const suggestBrand  = (name)                              =>
  request('/brands/suggest', { method: 'POST', body: JSON.stringify({ name }) });
export const previewBrand  = (keywords, platforms = ['tiktok', 'instagram']) =>
  request('/brands/preview', { method: 'POST', body: JSON.stringify({ keywords, platforms }) });
export const scanProfile   = (tiktok, instagram)                 =>
  request('/brands/profile-scan', { method: 'POST', body: JSON.stringify({ tiktok, instagram }) });

// ── Inbox (brand feed) ────────────────────────────────────────────────────────
export const getBrandInbox = (brandId) => request(`/inbox?brand_id=${brandId}`);

// ── Mentions ──────────────────────────────────────────────────────────────────
export const getMention      = (mentionId) => request(`/mentions/${mentionId}`);
export const postAction      = (mentionId, action, draft = null) =>
  request(`/mentions/${mentionId}/action`, { method: 'POST', body: JSON.stringify({ action, draft }) });
export const regenerateDraft = (mentionId) =>
  request(`/mentions/${mentionId}/regenerate`, { method: 'POST' });

// ── Comments ──────────────────────────────────────────────────────────────────
export const getComments      = (mentionId, refresh = false) =>
  request(`/mentions/${mentionId}/comments${refresh ? '?refresh=1' : ''}`);
export const commentAction    = (commentId, action, draft = null) =>
  request(`/comments/${commentId}/action`, { method: 'POST', body: JSON.stringify({ action, draft }) });
export const regenerateComment = (commentId) =>
  request(`/comments/${commentId}/regenerate`, { method: 'POST' });

// ── Analytics ─────────────────────────────────────────────────────────────────
export const getAnalytics    = (brandId) => request(`/analytics?brand_id=${brandId}`);

// ── Opportunities ─────────────────────────────────────────────────────────────
export const getOpportunities = (brandId) => request(`/opportunities?brand_id=${brandId}`);

// ── Brand stories ─────────────────────────────────────────────────────────────
export const getBrandStories  = (brandId) => request(`/stories?brand_id=${brandId}`);
export const getStory         = (id)      => request(`/stories/${id}`);
export const assessStory      = (id)      => request(`/stories/${id}/assess`, { method: 'POST' });
export const summarizeStory   = (id)      => request(`/stories/${id}/summarize`, { method: 'POST' });

// ── Digests ───────────────────────────────────────────────────────────────────
export const getBrandDigests  = (brandId) => request(`/brands/${brandId}/digests`);
export const createBrandDigest = (brandId) => request(`/brands/${brandId}/digest`, { method: 'POST' });

// ── Search ────────────────────────────────────────────────────────────────────
export const searchMentions  = (q) => request(`/search?query=${encodeURIComponent(q)}`);

// ── City explorer ─────────────────────────────────────────────────────────────
export const exploreCity     = (city, refresh = false) =>
  request('/explore/city', { method: 'POST', body: JSON.stringify({ city, refresh }) });
export const getCityReports  = () => request('/explore/cities');
