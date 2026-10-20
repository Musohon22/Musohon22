// Employee self-service portal (SCR-P0 … SCR-P8). Mobile-first; the employee sees only their own data.
import { createApi } from '/assets/core/api.js';
import { createRouter } from '/assets/core/router.js';
import { h, clear, btn, field, input, select, textarea, checkbox, toast, errorText, statusBadge, emptyState, load, kv, modal, showError, form } from '/assets/core/ui.js';
import { fmtDate, fmtTime, fmtDuration, fmtHours, fmtMonth, todayISO, addDays, weekday, WEEKDAYS, localToUTC, DEFAULT_TZ } from '/assets/core/format.js';

const root = document.getElementById('root');
const app = { me: null, home: null, tz: DEFAULT_TZ };
app.api = createApi({ realm: 'tenant', onUnauthorized: () => { if (app.me) { app.me = null; showLogin("Sessiya tugadi. Qaytadan kiring."); } } });

const NAV = [
  ['/me/', 'Bosh sahifa', '⌂'], ['/me/attendance', 'Davomat', '☰'], ['/me/schedule', 'Jadval', '▥'],
  ['/me/requests', "So'rovlar", '✉'], ['/me/profile', 'Profil', '👤'],
];
const ROUTES = [
  { path: '/', fn: renderHome }, { path: '/attendance', fn: renderAttendance }, { path: '/schedule', fn: renderSchedule },
  { path: '/hours', fn: renderHours }, { path: '/requests', fn: renderRequests }, { path: '/requests/leave', fn: renderLeaveForm },
  { path: '/requests/dispute', fn: renderDisputeForm }, { path: '/profile', fn: renderProfile },
];
let main, router;

// ---------------------------------------------------------------- auth (SCR-P0)
function authCard(children) {
  clear(root);
  root.appendChild(h('div', { class: 'login-wrap' }, h('div', { class: 'card pad-lg login-card stack' },
    h('div', { class: 'row' }, h('div', { class: 'avatar', style: { background: 'var(--c-primary)', color: '#fff' } }, 'FR'),
      h('div', {}, h('strong', {}, 'FRAS'), h('div', { class: 'caption' }, 'Xodim portali'))), children)));
}

function showLogin(message) {
  const q = new URLSearchParams(location.search);
  if (location.pathname.startsWith('/me/activate')) return showActivate(q.get('org'), q.get('token'));
  let saved = {}; try { saved = JSON.parse(localStorage.getItem('fras.portal') || '{}'); } catch { /* ignore */ }
  const org = input({ autocomplete: 'organization', value: q.get('org') || saved.org || '' });
  const login = input({ autocomplete: 'username', autocapitalize: 'none', autofocus: true });
  const pass = input({ type: 'password', autocomplete: 'current-password' });
  const err = h('div', { class: 'note danger', role: 'alert', hidden: !message }, message || '');
  const submit = btn('Kirish', { type: 'submit', size: 'l' });
  authCard(h('form', { class: 'stack', onsubmit: async (e) => {
    e.preventDefault(); err.hidden = true; submit.setLoading(true);
    try {
      const r = await app.api.post('/api/v1/auth/login', { org: org.value, login: login.value, password: pass.value }, { idempotent: false });
      try { localStorage.setItem('fras.portal', JSON.stringify({ org: org.value })); } catch { /* ignore */ }
      if (r.mfa_required) { location.href = '/app/'; return; }
      app.api.token = r.access_token; await boot();
    } catch (ex) { err.hidden = false; err.textContent = errorText(ex); pass.value = ''; }
    finally { submit.setLoading(false); }
  } }, h('h2', {}, 'Kirish'),
  field({ label: 'Tashkilot kodi', required: true, input: org }),
  field({ label: 'Tabel raqami', required: true, input: login, help: 'Masalan: t-1024' }),
  field({ label: 'Parol', required: true, input: pass }), err, submit,
  h('p', { class: 'caption' }, "Parolni unutdingizmi? HR bo'limiga murojaat qiling — ular yangi faollashtirish havolasini beradi.")));
}

function showActivate(org, token) {
  const p1 = input({ type: 'password', autocomplete: 'new-password', autofocus: true });
  const p2 = input({ type: 'password', autocomplete: 'new-password' });
  const err = h('div', { class: 'note danger', hidden: true });
  if (!org || !token) { authCard([h('h2', {}, "Havola noto'g'ri"), h('p', {}, "HR bergan havolani to'liq oching yoki yangisini so'rang.")]); return; }
  authCard(h('form', { class: 'stack', onsubmit: async (e) => {
    e.preventDefault(); err.hidden = true;
    if (p1.value !== p2.value) { err.hidden = false; err.textContent = 'Parollar mos emas'; return; }
    try {
      const r = await app.api.post('/api/v1/auth/accept-invite', { org, token, password: p1.value }, { idempotent: false });
      try { localStorage.setItem('fras.portal', JSON.stringify({ org })); } catch { /* ignore */ }
      history.replaceState({}, '', '/me/'); showLogin(); toast(`Hisob faollashtirildi. Login: ${r.login}`, 'success', { timeout: 10000 });
    } catch (ex) {
      err.hidden = false;
      err.textContent = ex.code === 'PASSWORD_WEAK' ? "Parol kamida 10 belgi, katta-kichik harf va raqamdan iborat bo'lsin"
        : ex.code === 'INVITE_INVALID' || ex.status === 404 ? "Havola eskirgan yoki ishlatilgan. HR'dan yangisini so'rang." : errorText(ex);
    }
  } }, h('h2', {}, 'Hisobni faollashtirish'), h('p', { class: 'muted' }, `Tashkilot: ${org}`),
  field({ label: 'Yangi parol', required: true, input: p1, help: 'Kamida 10 belgi, katta va kichik harf, raqam' }),
  field({ label: 'Parolni takrorlang', required: true, input: p2 }), err, btn('Faollashtirish', { type: 'submit', size: 'l' })));
}

async function logout() {
  try { await app.api.post('/api/v1/auth/logout', {}, { idempotent: false }); } catch { /* ignore */ }
  app.api.token = null; app.me = null; history.replaceState({}, '', '/me/'); showLogin();
}

// ---------------------------------------------------------------- shell
function renderShell() {
  clear(root);
  main = h('main', { class: 'portal-main', id: 'main', tabIndex: -1 });
  const nav = h('nav', { class: 'portal-nav', 'aria-label': 'Menyu' }, NAV.map(([href, label, icon]) =>
    h('a', { href, 'data-link': '' }, h('span', { 'aria-hidden': 'true' }, icon), h('span', {}, label))));
  const banner = h('div', { class: 'offline-banner', hidden: true }, "Aloqa yo'q. Ko'rsatilgan ma'lumotlar eskirgan bo'lishi mumkin.");
  app.api.listeners.add((online) => { banner.hidden = online; });
  root.appendChild(h('div', { class: 'portal' },
    h('header', { class: 'portal-head' }, h('span', { class: 'mark' }, 'FR'), h('strong', {}, app.me.tenant.name), h('span', { style: { flex: 1 } }),
      btn('', { variant: 'icon', icon: '⎋', title: 'Chiqish', onClick: logout })), banner, main, nav));
}

function setActive() {
  const p = location.pathname.replace(/\/+$/, '') || '/me';
  root.querySelectorAll('.portal-nav a').forEach((a) => {
    const href = a.getAttribute('href').replace(/\/+$/, '');
    a.classList.toggle('active', href === '/me' ? p === '/me' : p.startsWith(href));
  });
}

async function boot() {
  try { app.me = await app.api.get('/api/v1/me'); }
  catch (e) {
    if (e.status === 401 || e.status === 0) {
      try { await app.api.refresh(); app.me = await app.api.get('/api/v1/me'); } catch { return showLogin(); }
    } else return showLogin(errorText(e));
  }
  if (!app.me.user.employee_id || !app.me.permissions.includes('self.read')) {
    authCard([h('h2', {}, 'Bu hisob xodimga bog\'lanmagan'), h('p', { class: 'muted' }, "Xodim portali faqat xodim hisoblari uchun. Boshqaruv paneliga o'ting."),
      h('a', { class: 'btn', href: '/app/' }, 'Boshqaruv paneli'), btn('Chiqish', { variant: 'tertiary', onClick: logout })]);
    return;
  }
  renderShell();
  router = createRouter({ base: '/me', routes: ROUTES, notFound: () => router.go('/me/', { replace: true }),
    render: async (m) => {
      clear(main); setActive(); window.scrollTo(0, 0);
      try { await m.route.fn(main, m.params); } catch (e) { main.appendChild(h('div', { class: 'note danger' }, errorText(e))); }
    } });
  app.go = (p) => router.go(p);
  router.resolve();
}

const pageTitle = (title, sub) => h('div', { class: 'portal-title' }, h('h1', {}, title), sub ? h('div', { class: 'caption' }, sub) : null);

// ---------------------------------------------------------------- SCR-P1 home
async function renderHome(main) {
  await load(main, () => app.api.get('/api/v1/portal/home'), (r) => {
    app.home = r; app.tz = r.employee.timezone || DEFAULT_TZ;
    const t = r.today;
    const todayCard = h('div', { class: 'card stack' }, h('div', { class: 'row' }, h('h3', {}, 'Bugun'), h('span', { style: { flex: 1 } }), t ? statusBadge(t.status) : statusBadge('scheduled')),
      t ? kv([['Kelgan', t.first_in ? fmtTime(t.first_in, app.tz) : '—'], ['Ketgan', t.last_out ? fmtTime(t.last_out, app.tz) : '—'],
        ['Ishlagan', fmtDuration(t.worked_min)], t.late_min ? ['Kechikish', fmtDuration(t.late_min)] : null])
        : h('p', { class: 'muted' }, 'Bugun hali qayd yo\'q.'));
    const ns = r.next_shift;
    const m = r.month;
    const pct = m.planned_min ? Math.min(100, Math.round((m.worked_min / m.planned_min) * 100)) : 0;
    return [h('div', { class: 'portal-hello' }, h('h1', {}, `Salom, ${r.employee.name.split(' ')[0]}!`),
      h('div', { class: 'caption' }, `${r.employee.personnel_no} · ${r.employee.department} · ${r.employee.site}`)),
    bioNotice(r.employee.biometric_status),
    helloCheckinCard(),
    todayCard,
    h('div', { class: 'card stack' }, h('h3', {}, 'Keyingi smena'), ns
      ? h('div', {}, h('strong', {}, `${fmtDate(ns.date)} (${WEEKDAYS[weekday(ns.date)]})`), h('div', {}, `${ns.name}: ${ns.start}–${ns.end}`))
      : h('p', { class: 'muted' }, 'Yaqin 14 kunda smena rejalashtirilmagan.'), h('a', { href: '/me/schedule', 'data-link': '' }, "To'liq jadval →")),
    h('div', { class: 'card stack' }, h('h3', {}, 'Shu oy'),
      h('div', { class: 'progress', role: 'progressbar', 'aria-valuenow': pct, 'aria-valuemin': 0, 'aria-valuemax': 100 }, h('span', { style: { width: `${pct}%` } })),
      kv([['Ishlangan', `${fmtHours(m.worked_min)} / ${fmtHours(m.planned_min)} soat`], ['Kechikishlar', `${m.late_count} marta`], ["Qo'shimcha ish", fmtDuration(m.overtime_min)]]),
      h('div', { class: 'row' }, h('a', { href: '/me/attendance', 'data-link': '' }, 'Davomat →'), h('a', { href: '/me/hours', 'data-link': '' }, 'Yillik soatlar →'))),
    h('div', { class: 'portal-actions' },
      btn("Ta'til / ruxsat so'rash", { size: 'l', onClick: () => app.go('/me/requests/leave') }),
      btn("Xatoni e'tiroz qilish", { variant: 'secondary', size: 'l', onClick: () => app.go('/me/requests/dispute') })),
    r.open_requests ? h('a', { class: 'note info', href: '/me/requests', 'data-link': '' }, `Ko'rib chiqilayotgan so'rovlar: ${r.open_requests}`) : null];
  });
}

function bioNotice(status) {
  if (status === 'active') return null;
  const text = { none: "Yuz profilingiz hali ro'yxatdan o'tkazilmagan. Kirish uchun karta/PIN ishlating yoki HR bilan bog'laning.",
    declined: "Siz biometrikadan voz kechgansiz — karta/PIN orqali qayd qilasiz.", revoked: "Biometrik profilingiz o'chirilgan — karta/PIN ishlating.",
    pending_review: "Yuz profilingiz tekshiruvda." }[status];
  return text ? h('div', { class: 'note info' }, text) : null;
}

// ---------------------------------------------------------------- SCR-P2 attendance
async function renderAttendance(main) {
  const month = new URLSearchParams(location.search).get('month') || todayISO(app.tz).slice(0, 7);
  const prev = () => { const d = new Date(`${month}-15T00:00:00Z`); d.setUTCMonth(d.getUTCMonth() - 1); return d.toISOString().slice(0, 7); };
  const next = () => { const d = new Date(`${month}-15T00:00:00Z`); d.setUTCMonth(d.getUTCMonth() + 1); return d.toISOString().slice(0, 7); };
  const isCurrent = month >= todayISO(app.tz).slice(0, 7);
  main.append(pageTitle('Davomatim'), h('div', { class: 'row', style: { justifyContent: 'space-between', margin: '8px 0' } },
    btn('‹', { variant: 'secondary', title: 'Oldingi oy', onClick: () => app.go(`/me/attendance?month=${prev()}`) }),
    h('strong', {}, fmtMonth(month)),
    btn('›', { variant: 'secondary', title: 'Keyingi oy', disabled: isCurrent ? 'Kelajak oy' : false, onClick: () => { if (!isCurrent) app.go(`/me/attendance?month=${next()}`); } })));
  const box = h('div'); main.append(box,
    h('div', { class: 'btn-bar', style: { marginTop: '12px' } }, btn('Tabel PDF', { variant: 'secondary', icon: '⤓', onClick: () => app.api.download(`/api/v1/portal/hours.pdf?month=${month}`).catch(showError) })));
  await load(box, () => app.api.get('/api/v1/portal/attendance', { query: { month } }), (r) => {
    const today = todayISO(r.timezone);
    const days = r.days.filter((d) => d.date <= today).reverse();
    if (!days.length) return emptyState({ title: "Bu oy uchun ma'lumot yo'q" });
    return h('div', { class: 'stack' }, days.map((d) => {
      const s = d.summary;
      const evs = r.events.filter((e) => e.captured_at && s && ((s.first_in && e.captured_at >= s.first_in && (!s.last_out || e.captured_at <= s.last_out)) || e.captured_at.slice(0, 10) === d.date));
      const row = h('button', { class: 'portal-day', type: 'button', 'aria-expanded': 'false' },
        h('div', { class: 'd' }, h('strong', {}, d.date.slice(8)), h('span', { class: 'caption' }, WEEKDAYS[weekday(d.date)])),
        h('div', { class: 'm' }, s ? `${s.first_in ? fmtTime(s.first_in, r.timezone) : '—'} → ${s.last_out ? fmtTime(s.last_out, r.timezone) : '—'}` : '—',
          h('div', { class: 'caption' }, s ? fmtDuration(s.worked_min) : '')),
        h('div', {}, s ? statusBadge(s.status) : statusBadge(d.date === today ? 'scheduled' : 'off'), d.dispute ? h('div', { class: 'caption' }, `E'tiroz: ${statusLabelUz(d.dispute)}`) : null));
      const detail = h('div', { class: 'portal-day-detail', hidden: true },
        evs.length ? h('ul', {}, evs.map((e) => h('li', {}, `${fmtTime(e.captured_at, r.timezone)} · ${e.direction === 'in' ? 'Kirish' : 'Chiqish'} · ${e.gate || ''} · `, statusBadge(e.result)))) : h('p', { class: 'caption' }, "Qaydlar yo'q"),
        s?.late_min ? h('div', { class: 'caption' }, `Kechikish: ${fmtDuration(s.late_min)}`) : null,
        s?.overtime_min ? h('div', { class: 'caption' }, `Qo'shimcha: ${fmtDuration(s.overtime_min)}`) : null,
        d.can_dispute && !d.dispute ? btn("Bu kun bo'yicha e'tiroz", { variant: 'secondary', size: 's', onClick: () => app.go(`/me/requests/dispute?date=${d.date}`) })
          : !d.can_dispute ? h('div', { class: 'caption' }, "E'tiroz muddati o'tgan yoki davr yopilgan — HR bilan bog'laning.") : null);
      row.addEventListener('click', () => { detail.hidden = !detail.hidden; row.setAttribute('aria-expanded', String(!detail.hidden)); });
      return h('div', { class: 'card', style: { padding: '0' } }, row, detail);
    }));
  });
}
const statusLabelUz = (s) => ({ pending: 'kutilmoqda', approved: 'tasdiqlandi', rejected: 'rad etildi', cancelled: 'bekor' }[s] || s);

// ---------------------------------------------------------------- SCR-P3 schedule
async function renderSchedule(main) {
  main.append(pageTitle('Ish jadvalim', 'Keyingi 4 hafta'));
  const box = h('div'); main.append(box);
  await load(box, () => app.api.get('/api/v1/portal/schedule', { query: { from: todayISO(app.tz), days: 28 } }), (r) => h('div', { class: 'portal-week' },
    r.days.map((d) => h('div', { class: `portal-sday ${d.shift ? '' : 'off'} ${d.date === todayISO(app.tz) ? 'today' : ''}` },
      h('div', { class: 'caption' }, `${WEEKDAYS[weekday(d.date)]} ${d.date.slice(8)}.${d.date.slice(5, 7)}`),
      d.holiday ? h('div', {}, '★ Bayram') : d.shift ? [h('strong', {}, d.shift.code), h('div', { class: 'small' }, `${d.shift.start}–${d.shift.end}`)] : h('div', { class: 'muted' }, 'Dam')))));
}

// ---------------------------------------------------------------- hours (yearly)
async function renderHours(main) {
  const year = new Date().getFullYear();
  main.append(pageTitle('Ishlangan soatlar', String(year)));
  const box = h('div'); main.append(box);
  await load(box, () => app.api.get('/api/v1/portal/hours', { query: { year } }), (r) => [
    h('div', { class: 'card' }, h('h3', {}, "Yillik ta'til"), kv([['Huquq', `${r.vacation.entitled} kun`], ['Foydalanilgan / kutilmoqda', `${r.vacation.used_or_pending} kun`],
      ['Qolgan', `${Math.max(0, r.vacation.entitled - r.vacation.used_or_pending)} kun`]])),
    r.months.length ? h('div', { class: 'card', style: { marginTop: '12px' } }, h('table', { class: 'data' },
      h('thead', {}, h('tr', {}, ['Oy', 'Kunlar', 'Soat', "Qo'shimcha", 'Kechikish', ''].map((c) => h('th', {}, c)))),
      h('tbody', {}, r.months.map((m) => h('tr', {}, h('td', {}, m.month), h('td', { class: 'num' }, m.days), h('td', { class: 'num' }, fmtHours(m.worked_min)),
        h('td', { class: 'num' }, fmtHours(m.overtime_min)), h('td', { class: 'num' }, m.late_count),
        h('td', {}, btn('PDF', { variant: 'tertiary', size: 's', onClick: () => app.api.download(`/api/v1/portal/hours.pdf?month=${m.month}`).catch(showError) }))))))) : emptyState({ title: "Bu yil uchun ma'lumot yo'q" })]);
}

// ---------------------------------------------------------------- SCR-P4/P5 requests
async function renderRequests(main) {
  main.append(pageTitle("So'rovlarim"), h('div', { class: 'portal-actions' },
    btn("Ta'til / ruxsat", { onClick: () => app.go('/me/requests/leave') }), btn("E'tiroz", { variant: 'secondary', onClick: () => app.go('/me/requests/dispute') })));
  const box = h('div'); main.append(box);
  await load(box, () => app.api.get('/api/v1/portal/requests'), (r) => {
    const items = [...r.leaves.map((l) => ({ ...l, kind_label: l.type_name, when: l.start_date === l.end_date ? fmtDate(l.start_date) : `${fmtDate(l.start_date)} – ${fmtDate(l.end_date)}`, text: l.reason })),
      ...r.disputes.map((d) => ({ ...d, kind_label: "Davomat e'tirozi", when: fmtDate(d.work_date), text: d.comment.replace(/^\[xodim e'tirozi\]\s*/, '') }))]
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    if (!items.length) return emptyState({ icon: '✉', title: "So'rovlar yo'q" });
    return h('div', { class: 'stack', style: { marginTop: '12px' } }, items.map((x) => h('div', { class: 'card stack' },
      h('div', { class: 'row' }, h('strong', {}, x.kind_label), h('span', { style: { flex: 1 } }), statusBadge(x.status)),
      h('div', {}, x.when), h('div', { class: 'muted small' }, x.text),
      x.decision_comment ? h('div', { class: 'note small' }, `Javob: ${x.decision_comment}`) : null)));
  });
}

async function renderLeaveForm(main) {
  const today = todayISO(app.tz);
  const f = form([
    { name: 'type', label: 'Turi', type: 'select', required: true, options: [['vacation', "Yillik ta'til"], ['sick', 'Kasallik'], ['permission', 'Ruxsat (soatlik)'], ['business_trip', 'Xizmat safari'], ['unpaid', "Haq to'lanmaydigan"]] },
    { name: 'start_date', label: 'Boshlanish', type: 'date', required: true, min: addDays(today, -30) },
    { name: 'end_date', label: 'Tugash', type: 'date', required: true, min: addDays(today, -30) },
    { name: 'start_time', label: 'Dan (soat)', type: 'time', help: 'Faqat soatlik ruxsat uchun' }, { name: 'end_time', label: 'Gacha (soat)', type: 'time' },
    { name: 'reason', label: 'Sabab', type: 'textarea', required: true, minlength: 3 },
  ], { type: 'vacation', start_date: today, end_date: today });
  const typeSel = f.el.querySelector('[name="type"]');
  const times = [...f.el.querySelectorAll('[name="start_time"],[name="end_time"]')].map((i) => i.closest('.field'));
  const sync = () => times.forEach((t) => { t.hidden = typeSel.value !== 'permission'; });
  typeSel?.addEventListener('change', sync); sync();
  main.append(pageTitle("Ta'til yoki ruxsat so'rash", "So'rov rahbaringizga yuboriladi"), h('div', { class: 'card stack' }, f.el,
    h('div', { class: 'btn-bar' }, btn('Bekor', { variant: 'tertiary', onClick: () => history.back() }), btn('Yuborish', { onClick: async () => {
      if (!f.validate()) return;
      const v = f.values();
      if (v.end_date < v.start_date) { toast("Tugash sanasi boshlanishdan oldin bo'lmasin", 'warning'); return; }
      if (v.type !== 'permission') { delete v.start_time; delete v.end_time; }
      for (const k of Object.keys(v)) if (v[k] === null || v[k] === '') delete v[k];
      try { await app.api.post('/api/v1/portal/leaves', v); toast("So'rov yuborildi", 'success'); app.go('/me/requests'); }
      catch (e) {
        if (e.code === 'LEAVE_OVERLAP') toast("Bu sanalarda boshqa so'rov bor", 'error');
        else if (e.code === 'VACATION_BALANCE') toast("Ta'til kunlari yetarli emas", 'error');
        else showError(e, f);
      }
    } }))));
}

async function renderDisputeForm(main) {
  const q = new URLSearchParams(location.search);
  const today = todayISO(app.tz);
  const date = input({ type: 'date', value: q.get('date') || today, max: today, min: addDays(today, -30) });
  const kind = select([['add_event', "Qayd yo'q (kirdim/chiqdim, lekin qayd qilinmagan)"], ['change_time', "Vaqt noto'g'ri"], ['set_day_status', 'Xizmat safari / masofaviy edim']]);
  const direction = select([['in', 'Kirish'], ['out', 'Chiqish']]);
  const time = input({ type: 'time' });
  const eventSel = select([]);
  const dayStatus = select([['business_trip', 'Xizmat safari'], ['remote', 'Masofaviy ish']]);
  const comment = textarea({ rows: 4, minlength: 10, placeholder: "Nima bo'lganini qisqa yozing (kamida 10 belgi)" });
  const fDir = field({ label: "Yo'nalish", input: direction }), fTime = field({ label: "To'g'ri vaqt", input: time, required: true });
  const fEvent = field({ label: "Qaysi qayd noto'g'ri", input: eventSel }), fStatus = field({ label: 'Kun holati', input: dayStatus });
  const fComment = field({ label: 'Izoh', input: comment, required: true });
  let events = [];
  async function loadEvents() {
    try {
      const r = await app.api.get('/api/v1/portal/attendance', { query: { month: date.value.slice(0, 7) } });
      events = r.events.filter((e) => e.captured_at.slice(0, 10) === date.value);
      clear(eventSel).append(...(events.length ? events.map((e) => h('option', { value: e.id }, `${fmtTime(e.captured_at, app.tz)} ${e.direction === 'in' ? 'kirish' : 'chiqish'}`)) : [h('option', { value: '' }, "Bu kunda qayd yo'q")]));
    } catch { /* shown on submit */ }
  }
  const sync = () => { const k = kind.value; fDir.hidden = k !== 'add_event'; fTime.hidden = k === 'set_day_status'; fEvent.hidden = k !== 'change_time'; fStatus.hidden = k !== 'set_day_status'; };
  kind.addEventListener('change', sync); date.addEventListener('change', loadEvents); sync(); loadEvents();
  main.append(pageTitle("Davomat bo'yicha e'tiroz", "Oxirgi 30 kun uchun. HR yoki rahbar ko'rib chiqadi (odatda 3 ish kuni)."),
    h('div', { class: 'card stack' }, field({ label: 'Sana', input: date, required: true }), field({ label: 'Muammo', input: kind }), fDir, fEvent, fTime, fStatus, fComment,
      h('div', { class: 'btn-bar' }, btn('Bekor', { variant: 'tertiary', onClick: () => history.back() }), btn('Yuborish', { onClick: async () => {
        fComment.setError(null); fTime.setError(null);
        if (comment.value.trim().length < 10) { fComment.setError('Kamida 10 belgi'); return; }
        const body = { work_date: date.value, kind: kind.value, comment: comment.value.trim() };
        if (kind.value !== 'set_day_status') {
          if (!time.value) { fTime.setError('Vaqtni kiriting'); return; }
          body.new_time = localToUTC(date.value, time.value, app.tz);
        }
        if (kind.value === 'add_event') body.direction = direction.value;
        if (kind.value === 'change_time') { if (!eventSel.value) { toast("Bu kunda o'zgartiriladigan qayd yo'q — \"Qayd yo'q\" turini tanlang", 'warning'); return; } body.event_id = eventSel.value; }
        if (kind.value === 'set_day_status') body.day_status = dayStatus.value;
        try { const r = await app.api.post('/api/v1/portal/disputes', body); toast(`E'tiroz yuborildi. Javob muddati: ${fmtDate(r.sla_due)}`, 'success'); app.go('/me/requests'); }
        catch (e) {
          if (e.code === 'PERIOD_LOCKED') toast("Bu davr yopilgan. HR bilan bog'laning.", 'error');
          else if (e.code === 'DISPUTE_TOO_OLD') toast("30 kundan eski kunlar uchun HR'ga murojaat qiling", 'error');
          else showError(e);
        }
      } }))));
}

// ---------------------------------------------------------------- SCR-P6..P8 profile, consent, password
async function renderProfile(main) {
  const home = app.home || await app.api.get('/api/v1/portal/home');
  const e = home.employee;
  const lang = select([['uz', "O'zbek"], ['ru', 'Русский']], { value: app.me.user.language });
  lang.addEventListener('change', async () => { try { await app.api.patch('/api/v1/me', { language: lang.value }); toast('Saqlandi', 'success'); } catch (er) { showError(er); } });
  const cur = input({ type: 'password', autocomplete: 'current-password' }), nw = input({ type: 'password', autocomplete: 'new-password' });
  const fc = field({ label: 'Joriy parol', input: cur }), fn = field({ label: 'Yangi parol', input: nw, help: 'Kamida 10 belgi, katta-kichik harf va raqam' });
  main.append(pageTitle('Profil'),
    h('div', { class: 'card' }, kv([['Ism', e.name], ['Tabel raqami', e.personnel_no], ["Bo'lim", e.department], ['Obyekt', e.site], ['Biometrik holat', statusBadge(e.biometric_status)]]),
      h('p', { class: 'caption' }, "Ma'lumotlarda xato bo'lsa, HR bo'limiga murojaat qiling.")),
    h('div', { class: 'card stack', style: { marginTop: '12px' } }, field({ label: 'Til', input: lang })),
    h('div', { class: 'card stack', style: { marginTop: '12px' } }, h('h3', {}, "Parolni o'zgartirish"), fc, fn, btn("O'zgartirish", { variant: 'secondary', onClick: async () => {
      fc.setError(null); fn.setError(null);
      try { await app.api.post('/api/v1/me/password', { current: cur.value, new: nw.value }, { idempotent: false }); cur.value = nw.value = ''; toast("Parol o'zgartirildi", 'success'); }
      catch (er) { if (er.code === 'PASSWORD_MISMATCH') fc.setError("Joriy parol noto'g'ri"); else if (er.code === 'PASSWORD_WEAK' || er.status === 422) fn.setError('Parol talabga javob bermaydi'); else showError(er); }
    } })),
    passkeyBlock(),
    consentBlock(e),
    h('div', { class: 'card stack', style: { marginTop: '12px' } }, h('h3', {}, "Shaxsiy ma'lumotlar"),
      h('p', { class: 'small' }, "Yuz tasviringizdan faqat matematik shablon saqlanadi va faqat davomat uchun ishlatiladi. Ishdan ketganingizdan so'ng belgilangan muddatda o'chiriladi. Batafsil — korxona maxfiylik siyosatida."),
      btn('Chiqish', { variant: 'tertiary', onClick: logout })));
}

function consentBlock(e) {
  const box = h('div', { class: 'card stack', style: { marginTop: '12px' } }, h('h3', {}, 'Biometrik rozilik'));
  if (!['active', 'pending_review'].includes(e.biometric_status)) {
    box.append(h('p', { class: 'muted' }, "Faol biometrik profil yo'q. Qayta ro'yxatdan o'tish uchun HR bilan bog'laning."));
    return box;
  }
  box.append(h('p', { class: 'small' }, "Rozilikni istalgan vaqtda qaytarib olishingiz mumkin. Bu ish joyingizga ta'sir qilmaydi — davomat karta/PIN orqali davom etadi."),
    btn('Rozilikni qaytarib olish', { variant: 'danger', onClick: () => {
      const ok = checkbox("Tushundim: yuz profilim o'chiriladi va men karta/PIN orqali qayd qilaman");
      const confirmBtn = btn("Ha, o'chirish", { variant: 'danger', onClick: async () => {
        if (!ok.querySelector('input').checked) { toast('Avval tasdiqlang', 'warning'); return; }
        try { const r = await app.api.post('/api/v1/portal/consent/withdraw', { understood: true }); m.close(); toast(r.message, 'success', { timeout: 10000 }); app.home = null; app.go('/me/profile'); }
        catch (er) { showError(er); }
      } });
      const m = modal({ title: 'Biometrik rozilikni qaytarib olish', body: h('div', { class: 'stack' },
        h('ul', {}, h('li', {}, "Yuz shabloningiz darhol o'chiriladi"), h('li', {}, 'Terminallar sizni yuz orqali tanimaydi'), h('li', {}, 'HR sizga karta/PIN beradi')), ok),
      footer: [btn('Bekor', { variant: 'tertiary', onClick: () => m.close() }), confirmBtn] });
    } }));
  return box;
}

// ---------------------------------------------------------------- laptop check-in with Windows Hello (passkey)
// Windows Hello checks the person on the laptop (IR face camera, fingerprint or Hello PIN) and signs the
// server's one-time challenge with a key kept in the laptop's TPM. The face itself never leaves the laptop.
const toBuf = (s) => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((s.length + 3) % 4)), (c) => c.charCodeAt(0));
const toB64u = (b) => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

async function helloAvailable() {
  try { return !!window.PublicKeyCredential && await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable(); }
  catch { return false; }
}

function helloError(e) {
  if (e?.name === 'NotAllowedError') return "Bekor qilindi yoki vaqt tugadi. Qaytadan urinib ko'ring.";
  if (e?.name === 'InvalidStateError') return "Bu noutbuk allaqachon ulangan.";
  if (e?.name === 'SecurityError') return "Xavfsizlik xatosi: sahifa korxona manzilidan (HTTPS) ochilishi kerak.";
  return errorText(e);
}

const CHECKIN_ERRORS = {
  NO_ACTIVE_PASSKEY: "Bu noutbuk hali HR tomonidan tasdiqlanmagan.", PASSKEY_NOT_ACTIVE: "Bu noutbuk tasdiqlanmagan yoki o'chirilgan.",
  PASSKEY_CLONED: "Xavfsizlik sababli bu noutbuk kaliti bloklandi. HR bilan bog'laning.", WEBAUTHN_UV_REQUIRED: "Windows Hello sizni tasdiqlamadi.",
  WEBAUTHN_CHALLENGE: "So'rov eskirdi — qaytadan bosing.", SELF_CHECKIN_DISABLED: "Korxona noutbukdan qayd qilishni yoqmagan.",
};

function helloCheckinCard() {
  const box = h('div', { class: 'card stack', hidden: true });
  (async () => {
    let r; try { r = await app.api.get('/api/v1/portal/passkeys'); } catch { return; }
    if (!r.policy.enabled) return;
    box.hidden = false;
    const active = r.items.filter((x) => x.status === 'active');
    const status = h('div', { role: 'status', 'aria-live': 'polite' });
    box.append(h('div', { class: 'row' }, h('h3', {}, 'Noutbukdan qayd qilish'), h('span', { style: { flex: 1 } }), h('span', { class: 'badge info' }, 'Windows Hello')));
    if (!(await helloAvailable())) {
      box.append(h('p', { class: 'muted small' }, "Bu qurilmada Windows Hello (yoki boshqa ichki autentifikator) topilmadi. Windows sozlamalarida Hello'ni yoqing yoki terminaldan foydalaning."));
      return;
    }
    if (!active.length) {
      const pending = r.items.some((x) => x.status === 'pending');
      box.append(h('p', { class: 'muted small' }, pending ? "Noutbukingiz HR tasdig'ini kutmoqda." : "Avval shu noutbukni profilingizga ulang."),
        pending ? null : h('a', { href: '/me/profile', 'data-link': '' }, 'Profil → Windows Hello →'));
      return;
    }
    if (r.policy.networks_configured && !r.policy.on_office_network) {
      box.append(h('div', { class: 'note warning small' }, r.policy.outside_network === 'deny'
        ? "Siz korxona tarmog'ida emassiz — bu yerdan qayd qilib bo'lmaydi." : "Siz korxona tarmog'ida emassiz — qayd HR tekshiruviga tushadi."));
    }
    const go = (direction) => async () => {
      status.className = ''; status.textContent = 'Windows Hello oynasiga qarang…';
      try {
        const opts = await app.api.post('/api/v1/portal/checkin/options', { direction }, { idempotent: false });
        const cred = await navigator.credentials.get({ publicKey: { challenge: toBuf(opts.challenge), rpId: opts.rpId, timeout: opts.timeout,
          userVerification: 'required', allowCredentials: opts.allowCredentials.map((c) => ({ type: 'public-key', id: toBuf(c.id), transports: c.transports })) } });
        const res = await app.api.post('/api/v1/portal/checkin', { credential_id: toB64u(cred.rawId), client_data_json: toB64u(cred.response.clientDataJSON),
          authenticator_data: toB64u(cred.response.authenticatorData), signature: toB64u(cred.response.signature) }, { idempotent: false });
        const kind = { accepted: 'success', duplicate: 'info', review: 'warning', denied: 'danger' }[res.result];
        status.className = `note ${kind}`; status.textContent = `${res.message} · ${fmtTime(res.captured_at, app.tz)}`;
        app.home = null;
      } catch (e) {
        status.className = 'note danger';
        status.textContent = e.code ? (CHECKIN_ERRORS[e.code] || errorText(e)) : helloError(e);
      }
    };
    box.append(h('div', { class: 'portal-actions' }, btn('→ Kirish', { size: 'l', onClick: go('in') }), btn('← Chiqish', { variant: 'secondary', size: 'l', onClick: go('out') })),
      status, h('div', { class: 'caption' }, "Yuzingizni Windows Hello noutbukning o'zida tekshiradi; serverga rasm yuborilmaydi."));
  })();
  return box;
}

function passkeyBlock() {
  const box = h('div', { class: 'card stack', style: { marginTop: '12px' } });
  const draw = async () => {
    clear(box).append(h('h3', {}, 'Windows Hello (noutbuk orqali qayd)'));
    let r; try { r = await app.api.get('/api/v1/portal/passkeys'); } catch (e) { box.append(h('div', { class: 'note danger' }, errorText(e))); return; }
    if (!r.policy.enabled) { box.append(h('p', { class: 'muted small' }, "Korxonangiz noutbukdan qayd qilishni hali yoqmagan.")); return; }
    box.append(h('p', { class: 'small' }, "Shu noutbukni ulasangiz, Windows Hello (yuz, barmoq izi yoki PIN) bilan kirish/chiqishni qayd qila olasiz. Kalit faqat shu noutbukda saqlanadi."),
      r.policy.require_approval ? h('div', { class: 'caption' }, "Yangi noutbukni HR tasdiqlaydi.") : null);
    const STATUS = { active: ['Faol', 'success'], pending: ['Tasdiq kutilmoqda', 'warning'] };
    if (r.items.length) {
      box.append(h('div', { class: 'stack' }, r.items.map((c) => h('div', { class: 'row', style: { borderTop: '1px solid var(--border)', paddingTop: '8px' } },
        h('div', { style: { flex: 1, minWidth: 0 } }, h('strong', {}, c.label), h('div', { class: 'caption' }, `${c.authenticator} · ulangan ${fmtDate(c.created_at)}${c.last_used_at ? ` · oxirgi ${fmtDate(c.last_used_at)}` : ''}`)),
        h('span', { class: `badge ${STATUS[c.status]?.[1] || ''}` }, STATUS[c.status]?.[0] || c.status),
        btn("O'chirish", { variant: 'tertiary', size: 's', onClick: async () => {
          if (!window.confirm(`"${c.label}" o'chirilsinmi? Bu noutbukdan qayd qilib bo'lmay qoladi.`)) return;
          try { await app.api.del(`/api/v1/portal/passkeys/${c.id}`); toast("O'chirildi", 'success'); draw(); } catch (e) { showError(e); }
        } })))));
    }
    if (!(await helloAvailable())) { box.append(h('div', { class: 'note warning small' }, "Bu qurilmada Windows Hello topilmadi. Windows sozlamalari → Hisoblar → Kirish parametrlari → Windows Hello'ni yoqing.")); return; }
    if (r.policy.networks_configured && !r.policy.on_office_network) { box.append(h('div', { class: 'note warning small' }, "Noutbukni faqat korxona tarmog'ida ulash mumkin.")); return; }
    const label = input({ value: 'Ish noutbuki', maxlength: 60 });
    box.append(field({ label: 'Qurilma nomi', input: label }), btn('Shu noutbukni ulash', { onClick: async () => {
      try {
        const o = await app.api.post('/api/v1/portal/passkeys/options', {}, { idempotent: false });
        const cred = await navigator.credentials.create({ publicKey: { ...o, challenge: toBuf(o.challenge), user: { ...o.user, id: toBuf(o.user.id) },
          excludeCredentials: o.excludeCredentials.map((c) => ({ type: 'public-key', id: toBuf(c.id) })) } });
        const res = await app.api.post('/api/v1/portal/passkeys', { credential_id: toB64u(cred.rawId), client_data_json: toB64u(cred.response.clientDataJSON),
          attestation_object: toB64u(cred.response.attestationObject), label: label.value || 'Noutbuk' }, { idempotent: false });
        toast(res.status === 'pending' ? "Noutbuk ulandi. HR tasdiqlagach qayd qila olasiz." : 'Noutbuk ulandi', 'success', { timeout: 8000 });
        draw();
      } catch (e) {
        const msg = { PASSKEY_SYNCED_NOT_ALLOWED: "Bu passkey bulutda sinxronlanadi (telefon/parol menejeri). Faqat shu noutbukdagi Windows Hello qabul qilinadi.",
          OUTSIDE_OFFICE_NETWORK: "Noutbukni korxona tarmog'ida ulang.", PASSKEY_LIMIT: "Qurilmalar soni chegarasiga yetdingiz — eskisini o'chiring.",
          WEBAUTHN_UV_REQUIRED: "Windows Hello foydalanuvchini tasdiqlamadi." }[e.code];
        toast(msg || (e.code ? errorText(e) : helloError(e)), 'error', { timeout: 8000 });
      }
    } }));
  };
  draw();
  return box;
}

boot();
