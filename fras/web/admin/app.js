// Admin SPA shell (SCR-00, global layout F.1).
import { createApi } from '/assets/core/api.js';
import { createRouter } from '/assets/core/router.js';
import { h, clear, btn, field, input, toast, errorText, popover, emptyState, $ } from '/assets/core/ui.js';
import { t, setLang, getLang } from '/assets/core/i18n.js';
import { fmtTime, relTime, DEFAULT_TZ } from '/assets/core/format.js';

const root = document.getElementById('root');
export const app = {
  me: null, tz: DEFAULT_TZ, live: new EventTarget(), counts: {},
  can: (perm) => !!app.me?.permissions.includes(perm),
};
app.api = createApi({ realm: 'tenant', onUnauthorized: () => { if (app.me) { app.me = null; showLogin(); } } });

const NAV = [
  { group: 'Asosiy' },
  { path: '/dashboard', label: 'Dashboard', icon: '▦', perm: 'attendance.read' },
  { path: '/live', label: 'Jonli lenta', icon: '◉', perm: 'attendance.read' },
  { group: 'Xodimlar' },
  { path: '/employees', label: 'Xodimlar', icon: '👥', perm: 'employee.read' },
  { path: '/biometrics/reviews', label: 'Dublikat yuzlar', icon: '⧉', perm: 'biometric.review', count: 'duplicate_faces' },
  { group: 'Davomat' },
  { path: '/attendance/events', label: 'Davomat jurnali', icon: '☰', perm: 'attendance.read' },
  { path: '/attendance/timesheet', label: 'Tabel', icon: '▤', perm: 'attendance.read' },
  { path: '/attendance/anomalies', label: 'Anomaliyalar', icon: '⚠', perm: 'attendance.read', count: 'anomalies' },
  { path: '/approvals', label: 'Tasdiqlar', icon: '✔', perm: 'attendance.read', count: 'approvals' },
  { path: '/attendance/periods', label: 'Davrlar', icon: '🔒', perm: 'attendance.read' },
  { group: 'Rejalashtirish' },
  { path: '/shifts/schedule', label: 'Jadval', icon: '▥', perm: 'attendance.read' },
  { path: '/shifts/templates', label: 'Smenalar', icon: '◷', perm: 'org.read' },
  { path: '/shifts/calendar', label: 'Kalendar', icon: '📅', perm: 'org.read' },
  { path: '/leaves', label: "Ta'tillar", icon: '✈', perm: 'attendance.read' },
  { group: 'Tahlil' },
  { path: '/reports', label: 'Hisobotlar', icon: '📊', perm: 'report.view' },
  { path: '/roi', label: 'ROI', icon: '💹', perm: 'report.view' },
  { group: 'Infratuzilma' },
  { path: '/devices', label: 'Qurilmalar', icon: '📟', perm: 'device.read' },
  { group: 'Xavfsizlik' },
  { path: '/security/alerts', label: 'Ogohlantirishlar', icon: '🚨', perm: 'alert.read', count: 'alerts' },
  { path: '/security/users', label: 'Foydalanuvchilar', icon: '🔑', perm: 'user.manage' },
  { path: '/security/roles', label: 'Rollar', icon: '🛡', perm: 'role.read' },
  { path: '/security/sessions', label: 'Sessiyalar', icon: '⎋', perm: 'session.revoke' },
  { path: '/security/audit', label: 'Audit log', icon: '🧾', perm: 'audit.read' },
  { group: 'Tizim' },
  { path: '/settings', label: 'Sozlamalar', icon: '⚙', perm: 'settings.read' },
];

const ROUTES = [
  ['/dashboard', 'dashboard', 'render', 'attendance.read'], ['/live', 'dashboard', 'renderLive', 'attendance.read'],
  ['/employees', 'employees', 'renderList', 'employee.read'], ['/employees/new', 'employees', 'renderForm', 'employee.write'],
  ['/employees/import', 'employees', 'renderImport', 'employee.import'], ['/employees/duplicates', 'employees', 'renderDuplicates', 'employee.merge'],
  ['/employees/:id', 'employees', 'renderProfile', 'employee.read'], ['/employees/:id/edit', 'employees', 'renderForm', 'employee.write'],
  ['/employees/:id/enroll', 'enroll', 'render', 'biometric.enroll'], ['/biometrics/reviews', 'enroll', 'renderReviews', 'biometric.review'],
  ['/attendance/events', 'attendance', 'renderJournal', 'attendance.read'], ['/attendance/timesheet', 'attendance', 'renderTimesheet', 'attendance.read'],
  ['/attendance/anomalies', 'attendance', 'renderAnomalies', 'attendance.read'], ['/approvals', 'attendance', 'renderApprovals', 'attendance.read'],
  ['/attendance/periods', 'attendance', 'renderPeriods', 'attendance.read'],
  ['/shifts/schedule', 'shifts', 'renderSchedule', 'attendance.read'], ['/shifts/templates', 'shifts', 'renderTemplates', 'org.read'],
  ['/shifts/calendar', 'shifts', 'renderCalendar', 'org.read'], ['/shifts/history', 'shifts', 'renderHistory', 'audit.read'],
  ['/leaves', 'shifts', 'renderLeaves', 'attendance.read'],
  ['/reports', 'reports', 'renderCatalog', 'report.view'], ['/reports/exports', 'reports', 'renderExports', 'report.view'],
  ['/reports/:type', 'reports', 'renderReport', 'report.view'], ['/roi', 'reports', 'renderRoi', 'report.view'],
  ['/devices', 'devices', 'renderList', 'device.read'], ['/devices/register', 'devices', 'renderRegister', 'device.manage'],
  ['/devices/groups', 'devices', 'renderGroups', 'device.read'], ['/devices/firmware', 'devices', 'renderFirmware', 'device.read'],
  ['/devices/:id', 'devices', 'renderDetail', 'device.read'],
  ['/security/alerts', 'security', 'renderAlerts', 'alert.read'], ['/security/users', 'security', 'renderUsers', 'user.manage'],
  ['/security/roles', 'security', 'renderRoles', 'role.read'], ['/security/sessions', 'security', 'renderSessions', 'session.revoke'],
  ['/security/audit', 'security', 'renderAudit', 'audit.read'],
  ['/settings', 'settings', 'render', 'settings.read'], ['/settings/:section', 'settings', 'render', 'settings.read'],
  ['/profile', 'profile', 'render', null], ['/notifications', 'profile', 'renderNotifications', null],
].map(([path, mod, fn, perm]) => ({ path, mod, fn, perm }));

let main, sidebar, router;

// ---------------------------------------------------------------- auth screens
function authCard(children) {
  clear(root);
  root.appendChild(h('div', { class: 'login-wrap' }, h('div', { class: 'card pad-lg login-card stack' },
    h('div', { class: 'row' }, h('div', { class: 'avatar', style: { background: 'var(--c-primary)', color: '#fff' } }, 'FR'),
      h('div', {}, h('strong', {}, 'FRAS'), h('div', { class: 'caption' }, 'Davomat boshqaruvi'))), children)));
}

function showLogin(message) {
  const q = new URLSearchParams(location.search);
  if (location.pathname.startsWith('/app/invite')) return showInvite(q.get('org'), q.get('token'));
  let saved = {}; try { saved = JSON.parse(localStorage.getItem('fras.login') || '{}'); } catch { /* ignore */ }
  const org = input({ autocomplete: 'organization', value: saved.org || '', autofocus: !saved.org });
  const login = input({ autocomplete: 'username', autofocus: !!saved.org });
  const pass = input({ type: 'password', autocomplete: 'current-password' });
  const err = h('div', { class: 'note danger', role: 'alert', hidden: !message }, message || '');
  const submit = btn(t('Kirish'), { type: 'submit', size: 'l' });
  const f = h('form', { class: 'stack', onsubmit: async (e) => {
    e.preventDefault(); err.hidden = true; submit.setLoading(true);
    try {
      const r = await app.api.post('/api/v1/auth/login', { org: org.value, login: login.value, password: pass.value }, { idempotent: false });
      try { localStorage.setItem('fras.login', JSON.stringify({ org: org.value })); } catch { /* ignore */ }
      if (r.mfa_required) return showMfa(r.mfa_token);
      app.api.token = r.access_token; await boot();
    } catch (ex) { err.hidden = false; err.textContent = errorText(ex); pass.value = ''; pass.focus(); }
    finally { submit.setLoading(false); }
  } },
  h('h2', {}, 'Tizimga kirish'),
  field({ label: t('Tashkilot kodi'), required: true, input: org, help: 'Masalan: acme' }),
  field({ label: t('Login'), required: true, input: login, help: 'Email yoki tabel raqami' }),
  field({ label: t('Parol'), required: true, input: pass }), err, submit,
  h('div', { class: 'caption' }, '5 marta noto\'g\'ri urinishdan so\'ng hisob 15 daqiqaga bloklanadi.'),
  h('div', { class: 'row caption' }, h('a', { href: '/me/' }, 'Xodim portali'), h('span', {}, '·'), h('a', { href: '/roi' }, 'ROI kalkulyatori')));
  authCard(f);
}

function showMfa(mfaToken) {
  const code = input({ inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: 12, autofocus: true });
  const err = h('div', { class: 'note danger', role: 'alert', hidden: true });
  authCard(h('form', { class: 'stack', onsubmit: async (e) => {
    e.preventDefault();
    try { const r = await app.api.post('/api/v1/auth/mfa', { mfa_token: mfaToken, code: code.value }, { idempotent: false });
      app.api.token = r.access_token; await boot(); }
    catch (ex) { err.hidden = false; err.textContent = ex.code === 'MFA_TOKEN_INVALID' ? 'Vaqt tugadi, qaytadan kiring' : errorText(ex); code.select(); }
  } }, h('h2', {}, 'Ikki bosqichli tasdiq'), h('p', { class: 'muted' }, 'Autentifikator ilovasidagi 6 xonali kodni yoki zaxira kodni kiriting.'),
  field({ label: 'Kod', required: true, input: code }), err, btn('Tasdiqlash', { type: 'submit', size: 'l' }),
  btn('Orqaga', { variant: 'tertiary', onClick: () => showLogin() })));
}

function showInvite(org, token) {
  const p1 = input({ type: 'password', autocomplete: 'new-password', autofocus: true });
  const p2 = input({ type: 'password', autocomplete: 'new-password' });
  const err = h('div', { class: 'note danger', hidden: true });
  authCard(h('form', { class: 'stack', onsubmit: async (e) => {
    e.preventDefault();
    if (p1.value !== p2.value) { err.hidden = false; err.textContent = 'Parollar mos emas'; return; }
    try { await app.api.post('/api/v1/auth/accept-invite', { org, token, password: p1.value }, { idempotent: false });
      history.replaceState({}, '', '/app/'); showLogin(); toast('Hisob faollashtirildi. Endi kiring.', 'success'); }
    catch (ex) { err.hidden = false; err.textContent = ex.code === 'PASSWORD_WEAK' ? "Parol kamida 10 belgi, katta-kichik harf va raqamdan iborat bo'lsin" : errorText(ex); }
  } }, h('h2', {}, 'Hisobni faollashtirish'), h('p', { class: 'muted' }, `Tashkilot: ${org || '—'}`),
  field({ label: 'Yangi parol', required: true, input: p1, help: 'Kamida 10 belgi, katta va kichik harf, raqam' }),
  field({ label: 'Parolni takrorlang', required: true, input: p2 }), err, btn('Faollashtirish', { type: 'submit', size: 'l' })));
}

// ---------------------------------------------------------------- MFA enforcement screen
function showMfaSetup() {
  clear(root);
  const box = h('div', { class: 'stack' });
  authCard(box);
  import('./pages/profile.js').then((m) => m.mfaSetupBlock(box, async () => { await boot(); }));
}

// ---------------------------------------------------------------- shell
function navLink(item) {
  const a = h('a', { class: 'nav', href: `/app${item.path}`, 'data-link': '', title: t(item.label) },
    h('span', { class: 'ico', 'aria-hidden': 'true' }, item.icon), h('span', { class: 'label' }, t(item.label)));
  if (item.count) { const c = h('span', { class: 'count', hidden: true }); a.appendChild(c); a.dataset.count = item.count; }
  return a;
}

function renderShell() {
  clear(root);
  const shell = h('div', { class: 'app' });
  try { if (localStorage.getItem('fras.sidebar') === 'collapsed') shell.classList.add('collapsed'); } catch { /* ignore */ }
  const unread = h('span', { class: 'count', style: { position: 'absolute', top: '2px', right: '2px', background: 'var(--c-danger)', color: '#fff', borderRadius: '8px', fontSize: '10px', padding: '0 5px' }, hidden: true });
  const bell = btn('', { variant: 'icon', icon: '🔔', title: t('Bildirishnomalar'), onClick: () => openNotifications(bell) });
  bell.style.position = 'relative'; bell.appendChild(unread);
  const search = input({ type: 'search', placeholder: 'Xodim qidirish (/)', 'aria-label': t('Qidirish') });
  search.addEventListener('keydown', (e) => { if (e.key === 'Enter' && search.value.trim().length >= 2) router.go(`/app/employees?q=${encodeURIComponent(search.value.trim())}`); });
  const lang = h('select', { class: 'input', style: { width: '72px', height: '32px' }, 'aria-label': 'Til', onchange: (e) => { setLang(e.target.value); boot(); } },
    h('option', { value: 'uz' }, 'UZ'), h('option', { value: 'ru' }, 'RU'));
  lang.value = getLang();
  const userBtn = btn(app.me.user.name, { variant: 'tertiary', icon: '👤', onClick: () => popover(userBtn, h('div', { class: 'menu' },
    h('div', { class: 'caption', style: { padding: '6px 10px' } }, `${app.me.tenant.name} · ${app.me.roles.map((r) => r.name).join(', ')}`),
    h('button', { onclick: () => router.go('/app/profile') }, 'Profil va MFA'),
    h('button', { onclick: () => { document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'; } }, 'Yorug\' / qorong\'i rejim'),
    h('button', { class: 'danger', onclick: logout }, t('Chiqish')))) });
  userBtn.classList.add('hide-mobile');
  const header = h('header', { class: 'header' },
    btn('', { variant: 'icon', icon: '☰', title: 'Menyu', onClick: () => {
      if (window.innerWidth < 768) shell.classList.toggle('mobile-nav');
      else if (window.innerWidth < 1280) shell.classList.toggle('expanded');
      else { shell.classList.toggle('collapsed'); try { localStorage.setItem('fras.sidebar', shell.classList.contains('collapsed') ? 'collapsed' : ''); } catch { /* ignore */ } }
    } }),
    h('div', { class: 'logo' }, h('span', { class: 'mark' }, 'FR'), h('span', { class: 'hide-mobile' }, 'FRAS')),
    app.me.sites.length > 1 ? siteSelector() : h('span', { class: 'caption hide-mobile' }, app.me.sites[0]?.name || ''),
    h('div', { class: 'search' }, search), h('div', { class: 'spacer only-mobile' }), lang, bell, userBtn);
  sidebar = h('nav', { class: 'sidebar', 'aria-label': 'Asosiy menyu' });
  let pendingGroup = null;
  for (const item of NAV) {
    if (item.group) { pendingGroup = item.group; continue; }
    if (item.perm && !app.can(item.perm)) continue;
    if (pendingGroup) { sidebar.appendChild(h('div', { class: 'group' }, t(pendingGroup))); pendingGroup = null; }
    sidebar.appendChild(navLink(item));
  }
  main = h('main', { class: 'main', id: 'main', tabIndex: -1 });
  const clock = h('span', { class: 'tabular' });
  const conn = h('span', {}, '● Ulangan');
  const footer = h('footer', { class: 'footer' }, h('span', {}, 'FRAS v0.1'), h('span', {}, 'Server vaqti: ', clock, ` (${app.tz})`), conn,
    app.me.provider_dev ? h('span', { class: 'badge purple' }, 'DEV biometrika — haqiqiy tanish emas') : null);
  setInterval(() => { clock.textContent = fmtTime(new Date().toISOString(), app.tz, true); }, 1000);
  const banner = h('div', { class: 'offline-banner', hidden: true }, "Server bilan aloqa yo'q. Ma'lumotlar eskirgan bo'lishi mumkin; yozish amallari bajarilmaydi.");
  app.api.listeners.add((online) => { banner.hidden = online; conn.textContent = online ? '● Ulangan' : '○ Aloqa yo\'q'; });
  shell.append(header, sidebar, h('div', { style: { gridArea: 'main', minWidth: 0 } }, banner, main), footer);
  if (app.me.subscription && ['past_due', 'restricted', 'suspended'].includes(app.me.subscription.status)) {
    main.before(h('div', { class: `note ${app.me.subscription.status === 'suspended' ? 'danger' : 'warning'}`, style: { margin: '12px 24px 0' } },
      `Obuna holati: ${app.me.subscription.status}. Davomat va terminallar ishlashda davom etadi. `, h('a', { href: '/app/settings/billing', 'data-link': '' }, 'Batafsil')));
  }
  root.appendChild(shell);
  app.setUnread = (n) => { unread.hidden = !n; unread.textContent = n > 99 ? '99+' : n; };
  app.shell = shell;
}

function siteSelector() {
  const s = h('select', { class: 'input hide-mobile', style: { width: '180px', height: '32px' }, 'aria-label': 'Zavod' },
    h('option', { value: '' }, 'Barcha zavodlar'), app.me.sites.map((x) => h('option', { value: x.id }, x.name)));
  try { s.value = localStorage.getItem('fras.site') || ''; } catch { /* ignore */ }
  app.site = s.value || null;
  s.addEventListener('change', () => { app.site = s.value || null; try { localStorage.setItem('fras.site', s.value); } catch { /* ignore */ } router.resolve(); });
  return s;
}

async function openNotifications(anchor) {
  const list = h('div', { class: 'stack', style: { maxHeight: '420px', overflowY: 'auto' } }, h('div', { class: 'skeleton' }));
  const p = popover(anchor, h('div', { style: { width: '340px' } }, h('div', { class: 'row', style: { marginBottom: '8px' } }, h('strong', {}, t('Bildirishnomalar')),
    h('span', { style: { flex: 1 } }), btn('Hammasini o\'qildi', { variant: 'tertiary', size: 's', onClick: async () => { await app.api.post('/api/v1/notifications/read-all'); p.close(); refreshCounts(); } })), list));
  try {
    const r = await app.api.get('/api/v1/notifications');
    clear(list);
    if (!r.items.length) list.appendChild(emptyState({ icon: '🔔', title: "Bildirishnoma yo'q" }));
    for (const n of r.items.slice(0, 30)) {
      list.appendChild(h('a', { href: n.link || '#', 'data-link': n.link ? '' : undefined, class: 'card', style: { padding: '8px 10px', opacity: n.read_at ? 0.7 : 1, display: 'block', color: 'inherit' },
        onclick: () => { app.api.post(`/api/v1/notifications/${n.id}/read`); p.close(); setTimeout(refreshCounts, 300); } },
      h('div', { class: 'row' }, h('strong', { class: 'small' }, n.title), h('span', { style: { flex: 1 } }), h('span', { class: 'caption' }, relTime(n.created_at))),
      h('div', { class: 'small muted' }, n.body)));
    }
  } catch (e) { clear(list); list.appendChild(h('div', { class: 'note danger' }, errorText(e))); }
}

export async function refreshCounts() {
  try {
    const [att, notes] = await Promise.all([app.can('attendance.read') ? app.api.get('/api/v1/dashboard/attention') : {}, app.api.get('/api/v1/notifications', { query: { unread: 1 } })]);
    app.counts = att; app.setUnread?.(notes.unread);
    sidebar?.querySelectorAll('[data-count]').forEach((a) => {
      const key = a.dataset.count; let n = att[key] || 0;
      if (key === 'approvals') n = (att.approvals || 0) + (att.leaves || 0);
      const c = a.querySelector('.count'); c.hidden = !n; c.textContent = n;
    });
  } catch { /* shown elsewhere */ }
}

// ---------------------------------------------------------------- live updates (SSE)
let es = null;
function connectLive() {
  es?.close();
  if (!app.can('attendance.read') && !app.can('alert.read')) return;
  es = new EventSource(`/api/v1/live/stream?token=${encodeURIComponent(app.api.token)}`);
  for (const type of ['event', 'device', 'alert', 'period']) es.addEventListener(type, (e) => app.live.dispatchEvent(new CustomEvent(type, { detail: JSON.parse(e.data) })));
  es.onerror = () => { es.close(); setTimeout(async () => { try { await app.api.refresh(); } catch { /* login screen */ } if (app.me) connectLive(); }, 30000); };
}
app.live.addEventListener('alert', (e) => { toast(`Xavfsizlik ogohlantirishi: ${e.detail.kind}`, e.detail.severity === 'high' || e.detail.severity === 'critical' ? 'error' : 'warning'); refreshCounts(); });

async function logout() { try { await app.api.post('/api/v1/auth/logout', {}, { idempotent: false }); } catch { /* ignore */ } app.api.token = null; app.me = null; es?.close(); showLogin(); }

// ---------------------------------------------------------------- page rendering
const modules = {};
async function renderRoute(m) {
  if (!main) return;
  main.scrollTop = 0; window.scrollTo(0, 0);
  sidebar.querySelectorAll('a.nav').forEach((a) => a.classList.toggle('active', location.pathname.startsWith(a.getAttribute('href'))));
  app.shell?.classList.remove('mobile-nav');
  clear(main);
  if (m.forbidden) { main.appendChild(emptyState({ icon: '🔒', title: "Bu sahifaga ruxsatingiz yo'q", text: `Kerakli ruxsat: ${m.route.perm}` })); return; }
  try {
    modules[m.route.mod] ||= await import(`./pages/${m.route.mod}.js`);
    await modules[m.route.mod][m.route.fn](main, m.params, app);
  } catch (e) {
    console.error(e);
    main.appendChild(emptyState({ icon: '⚠', title: 'Sahifani yuklab bo\'lmadi', text: errorText(e) }));
  }
  main.focus({ preventScroll: true });
}

app.go = (p) => router.go(p.startsWith('/app') ? p : `/app${p}`);
app.query = () => router.query();
app.setQuery = (q) => router.setQuery(q);

async function boot() {
  try {
    app.me = await app.api.get('/api/v1/me');
  } catch (e) {
    if (e.status === 401) return showLogin();
    return authCard(h('div', { class: 'note danger' }, errorText(e)));
  }
  if (app.me.mfa_required && !app.me.user.mfa_enabled && !app.me.mfa_relaxed) {
    try { await app.api.get('/api/v1/attendance/periods'); } catch (e) { if (e.code === 'MFA_SETUP_REQUIRED') return showMfaSetup(); }
  }
  app.tz = app.me.sites[0]?.timezone || DEFAULT_TZ;
  try { const info = await app.api.get('/api/v1/system/info'); app.me.provider_dev = info.biometric_provider_dev; } catch { /* no permission */ }
  renderShell();
  router = createRouter({ base: '/app', routes: ROUTES, render: renderRoute, canAccess: (p) => app.can(p),
    notFound: () => { if (location.pathname === '/app' || location.pathname === '/app/') { router.go(app.can('attendance.read') ? '/app/dashboard' : '/app/profile', { replace: true }); } else { clear(main); main.appendChild(emptyState({ icon: '?', title: 'Sahifa topilmadi' })); } } });
  router.resolve();
  refreshCounts(); setInterval(refreshCounts, 60000);
  connectLive();
}

// keyboard shortcuts (spec F.6)
let gPressed = false;
document.addEventListener('keydown', (e) => {
  if (!app.me || ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
  if (e.key === '/') { e.preventDefault(); $('.header .search input')?.focus(); return; }
  if (e.key === '?') { toast('Tugmalar: / qidiruv · g d dashboard · g e xodimlar · g a jurnal · Esc yopish', 'info'); return; }
  if (e.key === 'g') { gPressed = true; setTimeout(() => { gPressed = false; }, 800); return; }
  if (gPressed) { const map = { d: '/dashboard', e: '/employees', a: '/attendance/events', r: '/reports' }; if (map[e.key]) app.go(map[e.key]); gPressed = false; }
});

setLang(getLang());
if (location.pathname.startsWith('/app/invite')) showInvite(new URLSearchParams(location.search).get('org'), new URLSearchParams(location.search).get('token'));
else if (app.api.token) boot(); else app.api.refresh().then(boot).catch(() => showLogin());
