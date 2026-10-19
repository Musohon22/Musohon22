// API client: bearer token in sessionStorage, silent refresh via HttpOnly cookie, uniform errors.

export class ApiError extends Error {
  constructor(status, code, message, details = {}, requestId = null) {
    super(message);
    this.status = status; this.code = code; this.details = details; this.requestId = requestId;
  }
  get fieldErrors() {
    const out = {};
    for (const f of this.details?.fields || []) out[f.field.replace(/^body\./, '')] = f.message;
    if (this.details?.field) out[this.details.field] = this.message;
    return out;
  }
}

export function createApi({ realm = 'tenant', onUnauthorized = () => {} } = {}) {
  const key = `fras.token.${realm}`;
  const refreshPath = realm === 'platform' ? '/api/v1/platform/auth/refresh' : '/api/v1/auth/refresh';
  let refreshing = null;

  const api = {
    online: true,
    listeners: new Set(),
    get token() { try { return sessionStorage.getItem(key); } catch { return null; } },
    set token(v) { try { v ? sessionStorage.setItem(key, v) : sessionStorage.removeItem(key); } catch { /* private mode */ } },

    setOnline(v) { if (api.online !== v) { api.online = v; api.listeners.forEach((fn) => fn(v)); } },

    async refresh() {
      if (!refreshing) {
        refreshing = fetch(refreshPath, { method: 'POST', credentials: 'same-origin', headers: { 'X-Requested-With': 'fras' } })
          .then(async (r) => {
            if (!r.ok) throw new ApiError(401, 'SESSION_EXPIRED', 'Session expired');
            const data = await r.json(); api.token = data.access_token; return data.access_token;
          })
          .finally(() => { setTimeout(() => { refreshing = null; }, 0); });
      }
      return refreshing;
    },

    async request(method, path, { body, query, headers = {}, raw = false, form = null, idempotent = true, retry = true } = {}) {
      let url = path;
      if (query) {
        const q = new URLSearchParams();
        for (const [k, v] of Object.entries(query)) {
          if (v === undefined || v === null || v === '' || (Array.isArray(v) && !v.length)) continue;
          q.set(k, Array.isArray(v) ? v.join(',') : v);
        }
        const s = q.toString(); if (s) url += (url.includes('?') ? '&' : '?') + s;
      }
      const h = { ...headers };
      if (api.token) h.Authorization = `Bearer ${api.token}`;
      let payload;
      if (form) payload = form;
      else if (body !== undefined) { h['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
      if (idempotent && method === 'POST' && !h['Idempotency-Key']) h['Idempotency-Key'] = crypto.randomUUID();
      let res;
      try {
        res = await fetch(url, { method, headers: h, body: payload, credentials: 'same-origin' });
        api.setOnline(true);
      } catch (e) {
        api.setOnline(false);
        throw new ApiError(0, 'ERR-NET', 'Server bilan aloqa yo\'q');
      }
      if (res.status === 401 && retry && path !== refreshPath) {
        let code = '';
        try { code = (await res.clone().json()).error?.code; } catch { /* empty */ }
        if (code === 'TOKEN_EXPIRED' || code === 'UNAUTHORIZED') {
          try { await api.refresh(); return api.request(method, path, { body, query, headers, raw, form, idempotent, retry: false }); }
          catch { api.token = null; onUnauthorized(); }
        } else { api.token = null; onUnauthorized(); }
      }
      if (raw && res.ok) return res;
      const text = await res.text();
      const data = text ? (() => { try { return JSON.parse(text); } catch { return { raw: text }; } })() : null;
      if (!res.ok) {
        const e = data?.error || {};
        throw new ApiError(res.status, e.code || `HTTP_${res.status}`, e.message || res.statusText, e.details || {}, e.request_id);
      }
      return data;
    },
    get: (p, o) => api.request('GET', p, o),
    post: (p, body, o = {}) => api.request('POST', p, { ...o, body: body ?? {} }),
    put: (p, body, o = {}) => api.request('PUT', p, { ...o, body }),
    patch: (p, body, o = {}) => api.request('PATCH', p, { ...o, body }),
    del: (p, o) => api.request('DELETE', p, o),

    async download(path, filename, { method = 'GET', body } = {}) {
      const res = await api.request(method, path, { raw: true, body });
      const blob = await res.blob();
      const cd = res.headers.get('Content-Disposition') || '';
      const m = cd.match(/filename=([^;]+)/);
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = filename || (m ? m[1] : 'download');
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    },
  };
  return api;
}
