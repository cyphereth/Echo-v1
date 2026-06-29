// Low-level HTTP client — token storage + fetch wrapper.
// Domain-specific API call functions live in features/news/api.js and features/brand/api.js.

const TOKEN_KEY = 'echo_token';
export const getToken   = () => localStorage.getItem(TOKEN_KEY);
export const setToken   = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

export async function request(path, opts = {}) {
  const token = getToken();
  const { headers: optHeaders, ...restOpts } = opts;
  const res = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(optHeaders || {}),
    },
    ...restOpts,
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
