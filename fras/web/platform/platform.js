// SaaS operator panel (business tab 7): tenants, plans, invoices, payments, dunning, MRR, churn, tickets, audit.
// Platform staff see tenant metadata and billing only — never employee or biometric data.
import { createApi } from '/assets/core/api.js';
import { createRouter } from '/assets/core/router.js';
import { h, clear, btn, field, input, select, textarea, table, toast, errorText, statusBadge, badge, emptyState, load, kv, drawer, modal, showError, form, confirmDanger } from '/assets/core/ui.js';
import { fmtDate, fmtDateTime, fmtMoney, relTime } from '/assets/core/format.js';

const root = document.getElementById('root');
const app = { me: null };
app.api = createApi({ realm: 'platform', onUnauthorized: () => { if (app.me) { app.me = null; showLogin('Sessiya tugadi'); } } });
const P = (path) => `/api/v1/platform${path}`;

const NAV = [['/dashboard', 'Dashboard', '▦'], ['/tenants', 'Mijozlar', '🏭'], ['/invoices', 'Hisob-fakturalar', '🧾'], ['/dunning', 'Qarzdorlik', '⏳'],
  ['/plans', 'Tariflar', '💲'], ['/churn', 'Churn', '↘'], ['/tickets', "Qo'llab-quvvatlash", '🛟'], ['/audit', 'Audit', '🔍']];
const ROUTES = [
  { path: '/', fn: renderDashboard }, { path: '/dashboard', fn: renderDashboard }, { path: '/tenants', fn: renderTenants },
  { path: '/tenants/:id', fn: renderTenant }, { path: '/invoices', fn: renderInvoices }, { path: '/dunning', fn: renderDunning },
  { path: '/plans', fn: renderPlans }, { path: '/churn', fn: renderChurn }, { path: '/tickets', fn: renderTickets }, { path: '/audit', fn: renderAudit },
];
const SUB_STATUS = { trialing: ['Sinov', 'info'], active: ['Faol', 'success'], past_due: ["To'lov kechikdi", 'warning'], restricted: ['Cheklangan', 'warning'],
  suspended: "To'xtatilgan", cancelled: ['Bekor qilingan', ''], archived: ['Arxiv', ''], none: ["Yo'q", ''] };
const subBadge = (s) => { const v = SUB_STATUS[s]; return Array.isArray(v) ? badge(v[0], v[1]) : badge(v || s, s === 'suspended' ? 'danger' : ''); };
const INV_STATUS = { draft: ['Qoralama', ''], issued: ['Chiqarilgan', 'info'], overdue: ["Muddati o'tgan", 'danger'], paid: ["To'langan", 'success'], void: ['Bekor', ''], partially_paid: ["Qisman to'langan", 'warning'] };
const invBadge = (s) => badge(...(INV_STATUS[s] || [s, '']));
let main, router;

function pageHead(title, sub, actions = [], crumbs = null) {
  return h('div', {}, crumbs ? h('nav', { class: 'crumbs' }, crumbs.flatMap(([l, href], i) => [i ? h('span', {}, '/') : null, href ? h('a', { href: `/platform${href}`, 'data-link': '' }, l) : h('span', {}, l)])) : null,
    h('div', { class: 'page-head' }, h('div', { class: 'title' }, h('h1', {}, title), sub ? h('div', { class: 'caption' }, sub) : null), h('div', { class: 'actions' }, actions.filter(Boolean))));
}
async function act(fn, msg, f) { try { const r = await fn(); if (msg) toast(msg, 'success'); return r ?? true; } catch (e) { showError(e, f); return null; } }
// Mirrors PLATFORM_ROLES on the server (UI hint only; the API enforces it).
const ROLE_PERMS = { billing: ['platform.billing'], success: ['platform.tenants', 'platform.support'], support: ['platform.support'], security: ['platform.audit'] };
const can = (perm) => app.me && (app.me.user.role === 'owner' || (ROLE_PERMS[app.me.user.role] || []).includes(perm));

// ---------------------------------------------------------------- auth
function showLogin(message) {
  const email = input({ type: 'email', autocomplete: 'username', autofocus: true });
  const pass = input({ type: 'password', autocomplete: 'current-password' });
  const code = input({ inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: 6 });
  const fCode = field({ label: 'MFA kod', input: code }); fCode.hidden = true;
  const err = h('div', { class: 'note danger', role: 'alert', hidden: !message }, message || '');
  const submit = btn('Kirish', { type: 'submit', size: 'l' });
  clear(root).appendChild(h('div', { class: 'login-wrap' }, h('div', { class: 'card pad-lg login-card stack' },
    h('div', { class: 'row' }, h('div', { class: 'avatar', style: { background: 'var(--n-900)', color: '#fff' } }, 'FR'), h('div', {}, h('strong', {}, 'FRAS Platform'), h('div', { class: 'caption' }, 'Operator paneli'))),
    h('form', { class: 'stack', onsubmit: async (e) => {
      e.preventDefault(); err.hidden = true; submit.setLoading(true);
      try {
        const r = await app.api.post(P('/auth/login'), { email: email.value, password: pass.value, code: code.value || null }, { idempotent: false });
        if (r.mfa_required) { fCode.hidden = false; code.focus(); return; }
        app.api.token = r.access_token; await boot();
      } catch (ex) { err.hidden = false; err.textContent = errorText(ex); }
      finally { submit.setLoading(false); }
    } }, field({ label: 'Email', required: true, input: email }), field({ label: 'Parol', required: true, input: pass }), fCode, err, submit))));
}

async function logout() {
  try { await app.api.post(P('/auth/logout'), {}, { idempotent: false }); } catch { /* already expired */ }
  app.api.token = null; app.me = null; showLogin();
}

function renderShell() {
  clear(root);
  const shell = h('div', { class: 'app' });
  const sidebar = h('nav', { class: 'sidebar', 'aria-label': 'Menyu' }, NAV.map(([p, l, i]) => h('a', { class: 'nav', href: `/platform${p}`, 'data-link': '' }, h('span', { class: 'ico' }, i), h('span', { class: 'label' }, l))));
  main = h('main', { class: 'main', id: 'main', tabIndex: -1 });
  shell.append(h('header', { class: 'header' },
    btn('', { variant: 'icon', icon: '☰', title: 'Menyu', onClick: () => shell.classList.toggle(window.innerWidth < 768 ? 'mobile-nav' : 'collapsed') }),
    h('div', { class: 'logo' }, h('span', { class: 'mark', style: { background: 'var(--n-900)' } }, 'FR'), h('span', {}, 'FRAS Platform')), h('div', { class: 'spacer', style: { flex: 1 } }),
    h('span', { class: 'caption hide-mobile' }, `${app.me.user.name} · ${app.me.user.role}`), btn('Chiqish', { variant: 'tertiary', onClick: logout })),
  sidebar, h('div', { style: { gridArea: 'main', minWidth: 0 } }, main), h('footer', { class: 'footer' }, h('span', {}, 'Platforma xodimlari mijoz xodimlari va biometrik ma\'lumotlarini ko\'rmaydi')));
  root.appendChild(shell);
  app.sidebar = sidebar; app.shell = shell;
}

async function boot() {
  try { app.me = await app.api.get(P('/me')); }
  catch {
    try { await app.api.refresh(); app.me = await app.api.get(P('/me')); } catch { return showLogin(); }
  }
  renderShell();
  router = createRouter({ base: '/platform', routes: ROUTES, notFound: () => router.go('/platform/dashboard', { replace: true }),
    render: async (m) => {
      clear(main); app.shell.classList.remove('mobile-nav');
      app.sidebar.querySelectorAll('a').forEach((a) => a.classList.toggle('active', location.pathname.startsWith(a.getAttribute('href'))));
      try { await m.route.fn(main, m.params); } catch (e) { main.appendChild(h('div', { class: 'note danger' }, errorText(e))); }
    } });
  app.go = (p) => router.go(`/platform${p}`);
  router.resolve();
}

// ---------------------------------------------------------------- dashboard
async function renderDashboard(main) {
  main.append(pageHead('Platforma dashboard', "MRR — joriy obunalarning oylik qiymati (chegirmalar bilan). Sinovdagi mijozlar MRR'ga kirmaydi."));
  const box = h('div'); main.append(box);
  await load(box, () => app.api.get(P('/dashboard')), (d) => [
    h('div', { class: 'grid cols-4' }, kpi('MRR', fmtMoney(d.mrr_cents)), kpi('ARR', fmtMoney(d.arr_cents)), kpi('Yangi MRR (oy)', fmtMoney(d.new_mrr_cents)),
      kpi('Churn (oy)', `${d.churned_tenants_this_month} mijoz`, d.churned_tenants_this_month ? 'danger' : ''),
      kpi('Mijozlar', d.tenants), kpi("Muddati o'tgan fakturalar", d.overdue_invoices, d.overdue_invoices ? 'warning' : '', '/invoices?status=overdue'),
      kpi('Ochiq tiketlar', `${d.open_tickets}${d.sla_breached ? ` (${d.sla_breached} SLA buzilgan)` : ''}`, d.sla_breached ? 'danger' : '', '/tickets'),
      kpi('Offline qurilmalar', d.offline_devices, d.offline_devices ? 'warning' : '')),
    h('div', { class: 'card', style: { marginTop: '16px' } }, h('h3', {}, 'Obuna holatlari'), h('div', { class: 'chips' },
      Object.entries(d.tenants_by_status).map(([s, n]) => h('a', { class: 'chip', href: `/platform/tenants?status=${s}`, 'data-link': '' }, subBadge(s), ` ${n}`))))]);
}
function kpi(label, value, tone = '', href) {
  const el = h(href ? 'a' : 'div', { class: `card kpi ${tone}`, href: href ? `/platform${href}` : undefined, 'data-link': href ? '' : undefined, style: { color: 'inherit', display: 'block' } },
    h('div', { class: 'caption' }, label), h('div', { class: 'value', style: { fontSize: '26px', fontWeight: 700 } }, String(value)));
  return el;
}

// ---------------------------------------------------------------- tenants
async function renderTenants(main) {
  const q = new URLSearchParams(location.search);
  const search = input({ type: 'search', placeholder: 'Nomi yoki kod', value: q.get('q') || '' });
  const status = select([['', 'Barcha holatlar'], ...Object.keys(SUB_STATUS).filter((s) => s !== 'none').map((s) => [s, Array.isArray(SUB_STATUS[s]) ? SUB_STATUS[s][0] : SUB_STATUS[s]])], { value: q.get('status') || '' });
  const box = h('div');
  main.append(pageHead('Mijozlar', null, [can('platform.tenants') ? btn("+ Yangi mijoz", { onClick: () => tenantDrawer(refresh) }) : null]),
    h('div', { class: 'filters' }, search, status), box);
  async function refresh() {
    await load(box, () => app.api.get(P('/tenants'), { query: { q: search.value, status: status.value } }), (r) => table({ rows: r.items, onRow: (t) => app.go(`/tenants/${t.id}`),
      empty: emptyState({ icon: '🏭', title: "Mijoz topilmadi" }), columns: [
        { key: 'name', label: 'Mijoz', render: (t) => h('div', {}, h('strong', {}, t.name), h('div', { class: 'caption' }, t.slug)) },
        { key: 'plan_code', label: 'Tarif' }, { key: 'status', label: 'Obuna', render: (t) => subBadge(t.status) },
        { key: 'mrr_cents', label: 'MRR', num: true, render: (t) => fmtMoney(t.mrr_cents) },
        { key: 'usage', label: 'Xodimlar', num: true, render: (t) => `${t.usage.employees}${t.limits.employees ? ` / ${t.limits.employees}` : ''}` },
        { key: 'devices', label: 'Qurilmalar', num: true, render: (t) => t.usage.devices },
        { key: 'health', label: 'Sog\'liq', num: true, render: (t) => badge(String(t.health), t.health >= 70 ? 'success' : t.health >= 40 ? 'warning' : 'danger') },
        { key: 'deployment', label: 'Joylash' }, { key: 'created_at', label: 'Yaratilgan', render: (t) => fmtDate(t.created_at) }] }));
  }
  const upd = () => { const qs = new URLSearchParams(); if (search.value) qs.set('q', search.value); if (status.value) qs.set('status', status.value); history.replaceState({}, '', `/platform/tenants${qs.toString() ? `?${qs}` : ''}`); refresh(); };
  let t; search.addEventListener('input', () => { clearTimeout(t); t = setTimeout(upd, 300); }); status.addEventListener('change', upd);
  await refresh();
}

async function tenantDrawer(onDone) {
  const plans = (await app.api.get(P('/plans'))).items;
  const f = form([
    { name: 'name', label: 'Kompaniya nomi', required: true }, { name: 'slug', label: 'Tashkilot kodi', required: true, regex: '^[a-z0-9-]{2,32}$', regexMessage: 'Kichik lotin harflari, raqam, "-"', help: 'Kirishda ishlatiladi' },
    { name: 'legal_name', label: 'Yuridik nomi' }, { name: 'tin', label: 'STIR', regex: '^\\d{9}$', regexMessage: '9 ta raqam' },
    { name: 'plan_code', label: 'Tarif', type: 'select', required: true, options: plans.map((p) => [p.code, p.name]) },
    { name: 'billing_cycle', label: "To'lov davri", type: 'select', options: [['annual', 'Yillik'], ['monthly', 'Oylik']] },
    { name: 'trial_days', label: 'Sinov kunlari', type: 'number', min: 0, max: 60, help: '0 — sinovsiz' },
    { name: 'deployment', label: 'Joylash', type: 'select', options: [['cloud', 'Bulut'], ['onprem', 'On-premise']] },
    { name: 'admin_name', label: 'Administrator ismi', required: true }, { name: 'admin_email', label: 'Administrator email', type: 'email', required: true },
  ], { billing_cycle: 'annual', trial_days: 14, deployment: 'cloud', plan_code: 'business' });
  const d = drawer({ title: 'Yangi mijoz', body: f.el, footer: [btn('Bekor', { variant: 'tertiary', onClick: () => d.close() }), btn('Yaratish', { onClick: async () => {
    if (!f.validate()) return;
    const v = f.values(); for (const k of Object.keys(v)) if (v[k] === null) delete v[k];
    const r = await act(() => app.api.post(P('/tenants'), v), null, f);
    if (!r) return;
    d.close(); onDone?.();
    const link = input({ value: r.invite_link, readonly: true });
    const m = modal({ title: 'Mijoz yaratildi', body: h('div', { class: 'stack' }, h('p', {}, "Administrator uchun faollashtirish havolasi (7 kun amal qiladi). Uni xavfsiz kanal orqali yuboring — qayta ko'rsatilmaydi."), link),
      footer: [btn('Nusxalash', { variant: 'secondary', onClick: () => navigator.clipboard?.writeText(r.invite_link).then(() => toast('Nusxalandi', 'success')) }), btn('Yopish', { onClick: () => m.close() })] });
  } })] });
}

async function renderTenant(main, params) {
  const box = h('div'); main.append(box);
  const refresh = () => load(box, () => app.api.get(P(`/tenants/${params.id}`)), (r) => {
    const t = r.tenant, s = r.subscription;
    const actions = [
      can('platform.billing') ? btn("Tarifni o'zgartirish", { variant: 'secondary', onClick: () => planModal(r, refresh) }) : null,
      can('platform.billing') && s?.status === 'trialing' ? btn('Sinovni uzaytirish', { variant: 'secondary', onClick: () => daysModal('Sinovni uzaytirish', `/tenants/${t.id}/trial-extend`, 60, refresh) }) : null,
      can('platform.billing') && s && ['past_due', 'restricted', 'suspended'].includes(s.status) ? btn("To'lov kutilmoqda", { variant: 'secondary', onClick: () => daysModal("To'lov kutilmoqda (cheklovlar to'xtatiladi)", `/tenants/${t.id}/payment-pending`, 14, refresh) }) : null];
    return [pageHead(t.name, `${t.slug} · ${t.deployment}`, actions, [['Mijozlar', '/tenants'], [t.name]]),
      h('div', { class: 'grid cols-3' },
        h('div', { class: 'card' }, h('h3', {}, 'Obuna'), kv([['Holat', s ? subBadge(s.status) : '—'], ['Tarif', r.plan.name], ['MRR', fmtMoney(r.mrr_cents)], ["To'lov davri", s?.billing_cycle],
          ['Chegirma', s?.discount_pct ? `${s.discount_pct}%` : '—'], ['Sinov tugaydi', s?.trial_ends_at ? fmtDate(s.trial_ends_at) : '—'], ['Davr oxiri', s?.period_end ? fmtDate(s.period_end) : '—'],
          s?.payment_pending_until ? ["To'lov kutilmoqda", fmtDate(s.payment_pending_until)] : null])),
        h('div', { class: 'card' }, h('h3', {}, 'Foydalanish'), kv(Object.entries(r.usage).map(([k, v]) => [{ employees: 'Xodimlar', sites: 'Obyektlar', devices: 'Qurilmalar', admins: 'Administratorlar' }[k] || k, `${v}${r.plan.limits[k] ? ` / ${r.plan.limits[k]}` : ''}`])),
          h('div', { class: 'caption' }, `Qurilmalar: ${r.devices.map((d) => `${d.status} ${d.n}`).join(', ') || "yo'q"}`)),
        h('div', { class: 'card' }, h('h3', {}, `Sog'liq balli: ${r.health.score}/100`), h('div', { class: 'caption' }, "Churn xavfini erta aniqlash uchun"),
          kv(Object.entries(r.health.parts).map(([k, v]) => [{ active_ratio: 'Faol xodimlar', biometric_coverage: 'Biometrik qamrov', hr_activity: 'HR faolligi', timesheet_from_system: 'Tabel tizimdan', technical: 'Texnik holat', support: "Qo'llab-quvvatlash" }[k] || k, `${Math.round(v * 100)}% (vazn ${r.health.weights[k]})`])))),
      h('h2', { style: { marginTop: '24px' } }, 'Hisob-fakturalar'), invoiceTable(r.invoices, refresh),
      h('h2', { style: { marginTop: '24px' } }, 'Tiketlar'), table({ rows: r.tickets, empty: emptyState({ title: "Tiket yo'q" }), columns: [
        { key: 'subject', label: 'Mavzu' }, { key: 'priority', label: 'Muhimlik' }, { key: 'status', label: 'Holat' }, { key: 'created_at', label: 'Yaratilgan', render: (x) => relTime(x.created_at) }] })];
  });
  await refresh();
}

function planModal(r, onDone) {
  const plan = select([], {}); const disc = input({ type: 'number', min: 0, max: 50, value: r.subscription?.discount_pct || 0 });
  app.api.get(P('/plans')).then((p) => { p.items.forEach((x) => plan.appendChild(h('option', { value: x.code }, `${x.name}`))); plan.value = r.tenant.plan_code; });
  const err = h('div', { class: 'note danger', hidden: true });
  const m = modal({ title: "Tarifni o'zgartirish", body: h('div', { class: 'stack' }, field({ label: 'Tarif', input: plan }),
    field({ label: 'Chegirma, %', input: disc, help: "20% dan yuqori chegirma faqat platforma egasi tomonidan" }), err,
    h('div', { class: 'caption' }, "Pasaytirishda foydalanish yangi tarif limitidan oshsa, o'zgartirish rad etiladi.")),
  footer: [btn('Bekor', { variant: 'tertiary', onClick: () => m.close() }), btn('Saqlash', { onClick: async () => {
    try { await app.api.post(P(`/tenants/${r.tenant.id}/plan`), { plan_code: plan.value, discount_pct: Number(disc.value) || 0 }); m.close(); toast('Tarif yangilandi', 'success'); onDone(); }
    catch (e) {
      err.hidden = false;
      err.textContent = e.code === 'PLAN_DOWNGRADE_BLOCKED' ? `Foydalanish limitdan oshadi: ${Object.entries(e.details.over || {}).map(([k, [u, l]]) => `${k} ${u} > ${l}`).join(', ')}` : errorText(e);
    }
  } })] });
}

function daysModal(title, path, max, onDone) {
  const days = input({ type: 'number', min: 1, max, value: Math.min(7, max) }); const note = textarea({ rows: 3, placeholder: 'Sabab (kamida 5 belgi)' });
  const m = modal({ title, body: h('div', { class: 'stack' }, field({ label: `Kunlar (1–${max})`, input: days }), field({ label: 'Izoh', input: note, required: true })),
    footer: [btn('Bekor', { variant: 'tertiary', onClick: () => m.close() }), btn('Saqlash', { onClick: async () => {
      if (await act(() => app.api.post(P(path), { days: Number(days.value), note: note.value }), 'Saqlandi')) { m.close(); onDone(); }
    } })] });
}

// ---------------------------------------------------------------- invoices
function invoiceTable(rows, refresh, withTenant = false) {
  return table({ rows, empty: emptyState({ title: "Hisob-faktura yo'q" }), columns: [
    { key: 'number', label: 'Raqam', render: (i) => h('span', { class: 'mono' }, i.number) },
    withTenant ? { key: 'tenant_name', label: 'Mijoz', render: (i) => h('a', { href: `/platform/tenants/${i.tenant_id}`, 'data-link': '' }, i.tenant_name) } : null,
    { key: 'period', label: 'Davr', render: (i) => `${fmtDate(i.period_start)} – ${fmtDate(i.period_end)}` },
    { key: 'amount_cents', label: 'Summa', num: true, render: (i) => fmtMoney(i.amount_cents) },
    withTenant ? { key: 'paid_cents', label: "To'langan", num: true, render: (i) => fmtMoney(i.paid_cents || 0) } : null,
    { key: 'status', label: 'Holat', render: (i) => invBadge(i.status) }, { key: 'due_at', label: 'Muddat', render: (i) => fmtDate(i.due_at) },
    { key: 'act', label: '', render: (i) => (can('platform.billing') && !['paid', 'void'].includes(i.status) ? h('div', { class: 'row' },
      btn("To'lov", { variant: 'secondary', size: 's', onClick: () => paymentModal(i, refresh) }),
      btn('Bekor', { variant: 'tertiary', size: 's', onClick: () => confirmDanger({ title: `${i.number} ni bekor qilish`, consequences: ["Faktura qarzdorlik hisobidan chiqariladi", "Amal auditga yoziladi"], okLabel: 'Bekor qilish',
        onConfirm: async () => { await app.api.post(P(`/invoices/${i.id}/void`)); toast('Bekor qilindi', 'success'); refresh(); } }) })) : '') }].filter(Boolean) });
}

function paymentModal(inv, onDone) {
  const amount = input({ type: 'number', step: '0.01', min: 0.01, value: ((inv.amount_cents - (inv.paid_cents || 0)) / 100).toFixed(2) });
  const method = select([['bank_transfer', "Bank o'tkazmasi"], ['card', 'Karta'], ['cash', 'Naqd'], ['other', 'Boshqa']]);
  const ref = input({ placeholder: "To'lov topshiriqnomasi raqami" });
  const m = modal({ title: `To'lov: ${inv.number}`, body: h('div', { class: 'stack' }, field({ label: 'Summa ($)', input: amount, required: true }), field({ label: 'Usul', input: method }), field({ label: 'Asos / referens', input: ref, required: true })),
    footer: [btn('Bekor', { variant: 'tertiary', onClick: () => m.close() }), btn('Qayd qilish', { onClick: async () => {
      const cents = Math.round(Number(amount.value) * 100);
      if (!(cents > 0)) { toast("Summa noto'g'ri", 'warning'); return; }
      if (await act(() => app.api.post(P(`/invoices/${inv.id}/payments`), { amount_cents: cents, method: method.value, reference: ref.value }), "To'lov qayd qilindi")) { m.close(); onDone(); }
    } })] });
}

async function renderInvoices(main) {
  const st = select([['', 'Barchasi'], ...Object.entries(INV_STATUS).map(([k, [l]]) => [k, l])], { value: new URLSearchParams(location.search).get('status') || '' });
  const box = h('div');
  main.append(pageHead('Hisob-fakturalar', 'Hisob-kitob har kuni avtomatik; qo\'lda ham ishga tushirish mumkin', [can('platform.billing') ? btn('Billingni ishga tushirish', { variant: 'secondary', onClick: async () => {
    const r = await act(() => app.api.post(P('/invoices/run'), {}, { idempotent: false }));
    if (r) { toast(`Yangi fakturalar: ${r.invoices_issued}, holat o'zgarishlari: ${r.status_changes}`, 'success'); refresh(); }
  } }) : null]), h('div', { class: 'filters' }, st), box);
  const refresh = () => load(box, () => app.api.get(P('/invoices'), { query: { status: st.value } }), (r) => invoiceTable(r.items, refresh, true));
  st.addEventListener('change', refresh);
  await refresh();
}

// ---------------------------------------------------------------- dunning
async function renderDunning(main) {
  const box = h('div');
  main.append(pageHead('Qarzdorlik (dunning)', "Muddati o'tgan kunlar bo'yicha bosqichlar. Terminallar va davomat yozuvi hech qachon bloklanmaydi."), box);
  await load(box, () => app.api.get(P('/dunning')), (r) => [
    h('div', { class: 'chips', style: { marginBottom: '12px' } }, [...r.policy].sort((a, b) => a[0] - b[0]).map(([d, s]) => h('span', { class: 'chip' }, `${d}+ kun → `, subBadge(s)))),
    table({ rows: r.items, onRow: (x) => app.go(`/tenants/${x.tenant_id}`), empty: emptyState({ icon: '✓', title: 'Qarzdor mijoz yo\'q' }), columns: [
      { key: 'tenant', label: 'Mijoz' }, { key: 'overdue_days', label: 'Kechikish (kun)', num: true }, { key: 'status', label: 'Holat', render: (x) => subBadge(x.status) },
      { key: 'amount_cents', label: 'Qarz', num: true, render: (x) => fmtMoney(x.amount_cents || 0) },
      { key: 'next', label: 'Keyingi bosqich', render: (x) => (x.next_step ? h('span', {}, subBadge(x.next_step), ` ${x.next_step_in_days} kundan so'ng`) : '—') },
      { key: 'payment_pending_until', label: "To'lov kutilmoqda", render: (x) => (x.payment_pending_until ? fmtDate(x.payment_pending_until) : '—') }] })]);
}

// ---------------------------------------------------------------- plans
async function renderPlans(main) {
  const box = h('div');
  main.append(pageHead('Tariflar', "Narx o'zgarishi faqat yangi fakturalarga ta'sir qiladi (amaldagi mijozlar yangilanishgacha eski narxda)."), box);
  const refresh = () => load(box, () => app.api.get(P('/plans')), (r) => table({ rows: r.items, columns: [
    { key: 'name', label: 'Tarif', render: (p) => h('div', {}, h('strong', {}, p.name), h('div', { class: 'caption' }, `${p.code} · v${p.version}`)) },
    { key: 'price_model', label: 'Model' }, { key: 'price_cents', label: 'Narx', num: true, render: (p) => `${fmtMoney(p.price_cents)}${p.price_model === 'per_employee' || p.price_model === 'contract' ? ' / xodim' : ' / oy'}` },
    { key: 'min_monthly_cents', label: 'Minimal / oy', num: true, render: (p) => fmtMoney(p.min_monthly_cents) },
    { key: 'limits', label: 'Limitlar', wrap: true, render: (p) => Object.entries(p.limits).map(([k, v]) => `${k}: ${v ?? '∞'}`).join(', ') },
    { key: 'features', label: 'Imkoniyatlar', wrap: true, render: (p) => h('span', { class: 'caption' }, p.features.join(', ')) },
    { key: 'tenants', label: 'Mijozlar', num: true },
    { key: 'act', label: '', render: (p) => (app.me.user.role === 'owner' ? btn('Tahrirlash', { variant: 'tertiary', size: 's', onClick: () => planEdit(p, refresh) }) : '') }] }));
  await refresh();
}

function planEdit(p, onDone) {
  const price = input({ type: 'number', step: '0.01', value: (p.price_cents / 100).toFixed(2) });
  const min = input({ type: 'number', step: '0.01', value: (p.min_monthly_cents / 100).toFixed(2) });
  const limits = textarea({ rows: 5, class: 'input mono' }); limits.value = JSON.stringify(p.limits, null, 2);
  const feats = textarea({ rows: 3 }); feats.value = p.features.join(', ');
  const fl = field({ label: 'Limitlar (JSON)', input: limits });
  const m = modal({ title: `${p.name} tarifini tahrirlash`, body: h('div', { class: 'stack' }, h('div', { class: 'note warning' }, `Bu tarifdagi ${p.tenants} mijoz uchun narx keyingi yangilanishgacha o'zgarmaydi.`),
    field({ label: 'Narx ($)', input: price }), field({ label: 'Minimal oylik ($)', input: min }), fl, field({ label: 'Imkoniyatlar (vergul bilan)', input: feats })),
  footer: [btn('Bekor', { variant: 'tertiary', onClick: () => m.close() }), btn('Saqlash', { onClick: async () => {
    let lim; try { lim = JSON.parse(limits.value); fl.setError(null); } catch { fl.setError("JSON noto'g'ri"); return; }
    const body = { price_cents: Math.round(Number(price.value) * 100), min_monthly_cents: Math.round(Number(min.value) * 100), limits: lim, features: feats.value.split(',').map((s) => s.trim()).filter(Boolean) };
    if (await act(() => app.api.put(P(`/plans/${p.code}`), body), 'Tarif yangilandi')) { m.close(); onDone(); }
  } })] });
}

// ---------------------------------------------------------------- churn
async function renderChurn(main) {
  const box = h('div');
  main.append(pageHead('Churn tahlili', "Bekor qilish sabablari mijozning o'zi tanlaganidan olinadi"), box);
  await load(box, () => app.api.get(P('/churn')), (r) => [h('div', { class: 'grid cols-2' },
    h('div', { class: 'card' }, h('h3', {}, 'Sabablar'), r.reasons.length ? kv(r.reasons.map((x) => [x.reason, String(x.n)])) : emptyState({ title: "Bekor qilishlar yo'q" })),
    h('div', { class: 'card' }, h('h3', {}, 'Kogortalar (oy bo\'yicha)'), table({ dense: true, rows: r.cohorts, columns: [{ key: 'cohort', label: 'Kogorta' }, { key: 'tenants', label: 'Mijozlar', num: true },
      { key: 'churned', label: 'Ketgan', num: true }, { key: 'pct', label: 'Ketish %', num: true, render: (c) => `${c.tenants ? Math.round((c.churned / c.tenants) * 100) : 0}%` }] }))),
  h('h2', { style: { marginTop: '24px' } }, "So'nggi bekor qilishlar"), table({ rows: r.recent, empty: emptyState({ title: "Yo'q" }), columns: [
    { key: 'tenant', label: 'Mijoz' }, { key: 'reason', label: 'Sabab' }, { key: 'comment', label: 'Izoh', wrap: true }, { key: 'created_at', label: 'Sana', render: (x) => fmtDate(x.created_at) }] })]);
}

// ---------------------------------------------------------------- tickets
async function renderTickets(main) {
  const box = h('div');
  main.append(pageHead("Qo'llab-quvvatlash tiketlari", 'SLA: critical 4 soat, high 1 kun, normal 3 kun'), box);
  const refresh = () => load(box, () => app.api.get(P('/tickets')), (r) => table({ rows: r.items, rowClass: (t) => (t.sla_breached ? 'row-danger' : ''), empty: emptyState({ icon: '🛟', title: "Tiket yo'q" }),
    onRow: (t) => ticketDrawer(t, refresh), columns: [
      { key: 'subject', label: 'Mavzu', render: (t) => h('div', {}, h('strong', {}, t.subject), h('div', { class: 'caption' }, t.tenant)) },
      { key: 'priority', label: 'Muhimlik', render: (t) => badge(t.priority, { critical: 'danger', high: 'warning' }[t.priority] || '') },
      { key: 'status', label: 'Holat' }, { key: 'assignee', label: "Mas'ul" },
      { key: 'sla_due_at', label: 'SLA', render: (t) => (t.sla_breached ? badge(`Buzilgan · ${fmtDateTime(t.sla_due_at)}`, 'danger') : fmtDateTime(t.sla_due_at)) },
      { key: 'created_at', label: 'Yaratilgan', render: (t) => relTime(t.created_at) }] }));
  await refresh();
}

function ticketDrawer(t, onDone) {
  const status = select([['open', 'Ochiq'], ['in_progress', 'Jarayonda'], ['resolved', 'Hal qilindi'], ['closed', 'Yopildi']], { value: t.status });
  const prio = select([['low', 'Past'], ['normal', 'Oddiy'], ['high', 'Yuqori'], ['critical', 'Kritik']], { value: t.priority });
  const asg = input({ value: t.assignee || '', placeholder: "Mas'ul xodim" });
  const d = drawer({ title: t.subject, body: h('div', { class: 'stack' }, kv([['Mijoz', t.tenant], ['Kanal', t.channel], ['Yaratilgan', fmtDateTime(t.created_at)], ['SLA', fmtDateTime(t.sla_due_at)]]),
    h('div', { class: 'card', style: { whiteSpace: 'pre-wrap' } }, t.body), field({ label: 'Holat', input: status }), field({ label: 'Muhimlik', input: prio }), field({ label: "Mas'ul", input: asg })),
  footer: can('platform.support') ? [btn('Bekor', { variant: 'tertiary', onClick: () => d.close() }), btn('Saqlash', { onClick: async () => {
    if (await act(() => app.api.patch(P(`/tickets/${t.id}`), { status: status.value, priority: prio.value, assignee: asg.value || null }), 'Saqlandi')) { d.close(); onDone(); }
  } })] : [] });
}

// ---------------------------------------------------------------- audit
async function renderAudit(main) {
  const box = h('div');
  main.append(pageHead('Platforma auditi', "Platforma xodimlarining barcha amallari; zanjir yaxlitligi tekshiriladi"), box);
  await load(box, () => app.api.get(P('/audit')), (r) => [
    h('div', { class: `note ${r.chain.ok ? 'success' : 'danger'}`, style: { marginBottom: '12px' } }, r.chain.ok ? `✓ Audit zanjiri butun (${r.chain.records} yozuv)` : `✕ Audit zanjiri buzilgan: yozuv #${r.chain.broken_at_seq}`),
    table({ dense: true, rows: r.items, columns: [{ key: 'created_at', label: 'Vaqt', render: (a) => fmtDateTime(a.created_at) }, { key: 'actor_name', label: 'Kim' },
      { key: 'action', label: 'Amal', render: (a) => h('span', { class: 'mono' }, a.action) }, { key: 'object_type', label: 'Obyekt', render: (a) => `${a.object_type || ''} ${a.object_id ? a.object_id.slice(0, 8) : ''}` },
      { key: 'ip', label: 'IP' }] })]);
}

boot();
