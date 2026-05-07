const BASE = 'http://localhost:8000/api';

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  upload: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return fetch(`${BASE}/upload`, { method: 'POST', body: form }).then(r => {
      if (!r.ok) return r.json().then(e => { throw new Error(e.detail); });
      return r.json();
    });
  },

  runFpgrowth: (params: Record<string, unknown>) =>
    request(`${BASE}/fpgrowth`, { method: 'POST', body: JSON.stringify(params) }),

  getRules: (params: Record<string, string | number>) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString();
    return request(`${BASE}/rules?${qs}`);
  },

  getTransactions: (ruleIndex: number, round: string) =>
    request(`${BASE}/transactions?rule_index=${ruleIndex}&round=${round}`),

  getStats: () => request(`${BASE}/stats`),

  getTopology: () => request(`${BASE}/topology`),

  uploadTopology: (links: Record<string, unknown>[]) =>
    request(`${BASE}/topology/upload`, { method: 'POST', body: JSON.stringify({ links }) }),
};
