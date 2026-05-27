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
  upload: (files: FileList | File[]) => {
    const form = new FormData();
    const fileArr = Array.from(files as Iterable<File>);
    fileArr.forEach(f => form.append('files', f));
    return fetch(`${BASE}/upload`, { method: 'POST', body: form }).then(r => {
      if (!r.ok) return r.json().then(e => { throw new Error(e.detail); });
      return r.json();
    });
  },

  runFpgrowth: (params: Record<string, unknown>) =>
    request('/fpgrowth', { method: 'POST', body: JSON.stringify(params) }),

  getRules: (params: Record<string, any>) => {
    const qs = new URLSearchParams(Object.fromEntries(
      Object.entries(params).map(([k, v]) => [k, String(v)])
    )).toString();
    return request(`/rules?${qs}`);
  },

  getTransactions: (ruleIndex: number, round: string) =>
    request(`/transactions?rule_index=${ruleIndex}&round=${round}`),

  getStats: () => request('/stats'),

  getTopology: () => request('/topology'),

  uploadTopology: (links: Record<string, unknown>[]) =>
    request('/topology/upload', { method: 'POST', body: JSON.stringify({ links }) }),

  analyzeRule: (data: Record<string, unknown>) =>
    request('/analyze-rule', { method: 'POST', body: JSON.stringify(data) }),

  getDiagnosticTrees: () => request('/diagnostic-trees'),

  diagnoseScenario: (data: Record<string, unknown>) =>
    request('/diagnose-scenario', { method: 'POST', body: JSON.stringify(data) }),

  workOrderGuidance: (data: Record<string, unknown>) =>
    request('/work-order-guidance', { method: 'POST', body: JSON.stringify(data) }),

  getNENeighbors: (neNames: string[]) =>
    request('/topology/ne-neighbors', { method: 'POST', body: JSON.stringify({ ne_names: neNames }) }),

  validateAlarms: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return fetch('http://localhost:8000/api/validate', { method: 'POST', body: form }).then(r => {
      if (!r.ok) return r.json().then(e => { throw new Error(e.detail); });
      return r.json();
    });
  },

  matchRealtimeAlarms: (alarms: Record<string, unknown>[]) =>
    request('/match-alarms', { method: 'POST', body: JSON.stringify({ alarms }) }),

  analyzeFiberCuts: (workOrders: Record<string, unknown>[]) =>
    request('/fiber-cut-analysis', { method: 'POST', body: JSON.stringify({ work_orders: workOrders }) }),

  fiberCutDetect: () => request('/fiber-cut-detect', { method: 'POST' }),

  validateStore: () => request('/validate-store', { method: 'POST' }),
};
