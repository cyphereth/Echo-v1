// News-domain API functions — wired to /news/* and /topics/* backend endpoints.
// No scope helpers: all functions take topicId explicitly.
import { request } from '../../core/api/client';

// ── Topics ────────────────────────────────────────────────────────────────────
export const getTopics    = ()                       => request('/news/topics');
export const createTopic  = (name, keywords = [])   =>
  request('/news/topics', { method: 'POST', body: JSON.stringify({ name, keywords }) });

// ── News feed (inbox) ─────────────────────────────────────────────────────────
export const getNewsFeed  = (topicId)               => request(`/news/inbox?topic_id=${topicId}`);

// ── Stories ───────────────────────────────────────────────────────────────────
export const getNewsStories  = (topicId)            => request(`/news/stories?topic_id=${topicId}`);
export const getStory        = (id)                 => request(`/news/stories/${id}`);
export const assessStory     = (id)                 =>
  request(`/news/stories/${id}/assess`, { method: 'POST' });
export const summarizeStory  = (id)                 =>
  request(`/news/stories/${id}/summarize`, { method: 'POST' });

// ── Sources ───────────────────────────────────────────────────────────────────
export const getTopicSources   = (topicId)           => request(`/topics/${topicId}/sources`);
export const addTopicSource    = (topicId, handle)   =>
  request(`/topics/${topicId}/sources`, { method: 'POST', body: JSON.stringify({ handle }) });
export const deleteTopicSource = (topicId, probeId)  =>
  request(`/topics/${topicId}/sources/${probeId}`, { method: 'DELETE' });

// ── Digests ───────────────────────────────────────────────────────────────────
export const getTopicDigests    = (topicId)          => request(`/topics/${topicId}/digests`);
export const generateTopicDigest = (topicId)         =>
  request(`/topics/${topicId}/digest`, { method: 'POST' });
