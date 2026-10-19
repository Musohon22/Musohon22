// History-API router with :params, permission guards and URL query state.
export function createRouter({ base, routes, render, notFound, canAccess = () => true }) {
  const compiled = routes.map((r) => {
    const keys = [];
    const re = new RegExp('^' + (base + r.path).replace(/\/+$/, '').replace(/:(\w+)/g, (_, k) => { keys.push(k); return '([^/]+)'; }) + '/?$');
    return { ...r, re, keys };
  });
  const router = {
    current: null,
    match(pathname) {
      for (const r of compiled) {
        const m = pathname.match(r.re);
        if (m) return { route: r, params: Object.fromEntries(r.keys.map((k, i) => [k, decodeURIComponent(m[i + 1])])) };
      }
      return null;
    },
    go(path, { replace = false } = {}) {
      if (replace) history.replaceState({}, '', path); else history.pushState({}, '', path);
      router.resolve();
    },
    query() { return Object.fromEntries(new URLSearchParams(location.search)); },
    setQuery(obj) {
      const q = new URLSearchParams(location.search);
      for (const [k, v] of Object.entries(obj)) { if (v === undefined || v === null || v === '' || (Array.isArray(v) && !v.length)) q.delete(k); else q.set(k, Array.isArray(v) ? v.join(',') : v); }
      const s = q.toString();
      history.replaceState({}, '', location.pathname + (s ? `?${s}` : ''));
    },
    resolve() {
      const m = router.match(location.pathname.replace(/\/+$/, '') || base);
      if (!m) return notFound();
      if (m.route.perm && !canAccess(m.route.perm)) return render({ forbidden: true, route: m.route, params: m.params });
      router.current = m;
      return render(m);
    },
  };
  window.addEventListener('popstate', () => router.resolve());
  document.addEventListener('click', (e) => {
    const a = e.target.closest('a[data-link]');
    if (!a || e.ctrlKey || e.metaKey || e.shiftKey || a.target === '_blank') return;
    e.preventDefault(); router.go(a.getAttribute('href'));
  });
  return router;
}
