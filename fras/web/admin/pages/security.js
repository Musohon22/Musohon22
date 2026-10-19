// SCR-70 … SCR-74: users, roles, sessions & logins, audit log, security alerts.
import { h, clear, btn, select, input, field, form, table, tabs, modal, drawer, toast, statusBadge, badge, emptyState, load, kv, confirmDanger, showError, pagination, textarea, checkbox } from '/assets/core/ui.js';
import { fmtDateTime, relTime } from '/assets/core/format.js';
import { pageHead, orgTree, act } from './common.js';

const ROLE_LABELS = { super_admin: 'Super Admin', site_admin: 'Zavod administratori', hr_manager: 'HR Manager', hr_operator: 'HR Operator', shift_lead: "Smena boshlig'i", dept_head: "Bo'lim boshlig'i", security: 'Xavfsizlik xodimi', auditor: 'Auditor', employee: 'Xodim' };

async function roleScopeEditor(app) {
  const tree = await orgTree(app);
  const roles = (await app.api.get('/api/v1/roles').catch(() => ({ items: Object.keys(ROLE_LABELS).map((code) => ({ code, name: ROLE_LABELS[code] })) }))).items;
  const role = select(roles.filter((r) => r.code !== 'employee').map((r) => [r.code, r.name]));
  const scopeType = select([['global', 'Butun tashkilot'], ['site', 'Zavod'], ['department', "Bo'lim"], ['team', 'Brigada']]);
  const scopeId = select([]);
  const team = select([['A', 'A'], ['B', 'B'], ['C', 'C'], ['D', 'D']]);
  const sync = () => {
    clear(scopeId);
    const t = scopeType.value;
    if (t === 'site') tree.sites.forEach((s) => scopeId.appendChild(h('option', { value: s.id }, s.name)));
    if (t === 'department' || t === 'team') tree.sites.forEach((s) => s.departments.forEach((d) => scopeId.appendChild(h('option', { value: d.id }, `${d.name} (${s.name})`))));
    scopeId.parentElement && (scopeId.closest('.field').hidden = t === 'global');
    team.closest('.field') && (team.closest('.field').hidden = t !== 'team');
  };
  scopeType.addEventListener('change', sync);
  const el = h('div', { class: 'form-grid' }, field({ label: 'Rol', input: role }), field({ label: 'Doira', input: scopeType }), field({ label: 'Obyekt', input: scopeId }), field({ label: 'Brigada', input: team }));
  setTimeout(sync, 0);
  return { el, value: () => ({ role_code: role.value, scope_type: scopeType.value, scope_id: scopeType.value === 'global' ? null : scopeType.value === 'team' ? `${scopeId.value}:${team.value}` : scopeId.value }) };
}

export async function renderUsers(main, params, app) {
  const st = { q: '', limit: 50, offset: 0 };
  const box = h('div');
  const qIn = input({ type: 'search', placeholder: 'Ism yoki login' });
  qIn.addEventListener('change', () => { st.q = qIn.value; st.offset = 0; refresh(); });
  main.append(pageHead('Admin foydalanuvchilar', null, [btn("Foydalanuvchi qo'shish", { icon: '+', onClick: () => invite() })]), h('div', { class: 'filters' }, h('div', { class: 'field grow' }, h('label', {}, 'Qidirish'), qIn)), box);
  async function refresh() {
    await load(box, () => app.api.get('/api/v1/users', { query: st }), (r) => [table({ rows: r.items, onRow: (u) => openUser(u.id), columns: [
      { key: 'name', label: 'Ism' }, { key: 'login', label: 'Login' }, { key: 'roles', label: 'Rollar', wrap: true, render: (u) => h('span', { class: 'row' }, u.roles.map((x) => badge(`${x.role_name}${x.scope_type !== 'global' ? ` · ${x.scope_type}` : ''}`, 'primary'))) },
      { key: 'mfa', label: 'MFA', render: (u) => (u.mfa_enabled ? badge('Yoqilgan', 'success', '✓') : badge("Yo'q", 'warning')) }, { key: 'status', label: 'Holat', render: (u) => h('span', { class: 'row' }, statusBadge(u.status), u.locked ? badge('Qulflangan', 'danger') : null) },
      { key: 'last_login_at', label: 'Oxirgi kirish', render: (u) => (u.last_login_at ? relTime(u.last_login_at) : '—') }] }),
    pagination({ total: r.total, limit: st.limit, offset: st.offset, onChange: (p) => { Object.assign(st, p); refresh(); } })]);
  }
  async function invite() {
    const f = form([{ name: 'name', label: 'Ism', required: true, minlength: 2 }, { name: 'email', label: 'Email', required: true, type: 'email', regex: '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$', regexMessage: 'Email noto\'g\'ri' },
      { name: 'language', label: 'Til', type: 'select', options: [['uz', "O'zbek"], ['ru', 'Русский']] }]);
    const rs = await roleScopeEditor(app);
    const m = modal({ title: "Foydalanuvchi qo'shish", size: 'w640', body: [f.el, h('h3', {}, 'Rol va doira'), rs.el, h('div', { class: 'note' }, 'Taklif havolasi 48 soat amal qiladi. Imtiyozli rollar uchun MFA birinchi kirishda majburiy.')],
      footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn('Taklif yuborish', { onClick: async () => {
        if (!f.validate()) return;
        try { const r = await app.api.post('/api/v1/users', { ...f.values(), roles: [rs.value()] }); m.close(); refresh();
          modal({ title: 'Taklif yaratildi', body: [h('div', {}, 'Havola email orqali yuborildi. Zaxira uchun:'), h('input', { class: 'input mono', readonly: true, value: r.invite_link, onclick: (e) => e.target.select() })] }); }
        catch (e) { if (e.code === 'ROLE_NOT_GRANTABLE' || e.code === 'SCOPE_TOO_WIDE') toast(e.message, 'error'); else showError(e, f); }
      } })] });
  }
  async function openUser(id) {
    const d = drawer({ title: 'Foydalanuvchi', size: 'w720', body: h('div', { class: 'skeleton' }) });
    const reload = async () => {
      let u; try { u = await app.api.get(`/api/v1/users/${id}`); } catch (e) { d.setBody(h('div', { class: 'note danger' }, e.message)); return; }
      const rs = await roleScopeEditor(app);
      d.setBody([kv([['Ism', u.name], ['Login', u.login], ['Holat', statusBadge(u.status)], ['MFA', u.mfa_enabled ? 'yoqilgan' : "yo'q"], ['Oxirgi kirish', fmtDateTime(u.last_login_at, app.tz)]]),
        h('h3', {}, 'Rollar'), table({ dense: true, rows: u.roles, columns: [{ key: 'role_name', label: 'Rol' }, { key: 'scope_type', label: 'Doira' }, { key: 'scope_id', label: 'Obyekt' }, { key: 'valid_until', label: 'Muddat' },
          { key: 'x', label: '', render: (r) => btn('', { variant: 'icon', icon: '✕', title: 'Rolni olib tashlash', onClick: async () => { if (await act(() => app.api.del(`/api/v1/users/${u.id}/roles/${r.id}`), 'Rol olib tashlandi')) reload(); } }) }] }),
        h('div', { class: 'card stack' }, h('strong', {}, "Rol qo'shish"), rs.el, h('div', { class: 'btn-bar' }, btn("Qo'shish", { variant: 'secondary', onClick: async () => { if (await act(() => app.api.post(`/api/v1/users/${u.id}/roles`, rs.value()), "Rol qo'shildi")) reload(); } }))),
        h('h3', {}, 'Faol sessiyalar'), table({ dense: true, rows: u.sessions, columns: [{ key: 'created_at', label: 'Boshlangan', render: (s) => fmtDateTime(s.created_at, app.tz) }, { key: 'ip', label: 'IP' }, { key: 'user_agent', label: 'Qurilma', wrap: true },
          { key: 'x', label: '', render: (s) => btn('Bekor qilish', { variant: 'tertiary', size: 's', onClick: async () => { if (await act(() => app.api.post(`/api/v1/security/sessions/${s.id}/revoke`), 'Sessiya bekor qilindi')) reload(); } }) }] })]);
      d.setFooter([
        u.status === 'invited' ? btn('Taklifni qayta yuborish', { variant: 'secondary', onClick: async () => { const r = await act(() => app.api.post(`/api/v1/users/${u.id}/resend-invite`)); if (r) toast('Yuborildi', 'success'); } }) : null,
        u.mfa_enabled ? btn("MFA'ni qayta o'rnatish", { variant: 'secondary', onClick: () => confirmDanger({ title: "MFA'ni qayta o'rnatish", consequences: ['Barcha sessiyalar bekor qilinadi', 'Keyingi kirishda MFA qayta sozlanadi'], okLabel: 'Tasdiqlash', onConfirm: async () => { await app.api.post(`/api/v1/users/${u.id}/reset-mfa`); toast('MFA qayta o\'rnatildi', 'success'); reload(); } }) }) : null,
        btn('Parolni tiklash havolasi', { variant: 'secondary', onClick: async () => { const r = await act(() => app.api.post(`/api/v1/users/${u.id}/set-password`)); if (r) modal({ title: 'Bir martalik havola (24 soat)', body: h('input', { class: 'input mono', readonly: true, value: r.reset_link }) }); } }),
        u.status === 'blocked' ? btn('Blokdan chiqarish', { onClick: async () => { if (await act(() => app.api.post(`/api/v1/users/${u.id}/unblock`), 'Blokdan chiqarildi')) reload(); } })
          : btn('Bloklash', { variant: 'danger-outline', onClick: () => confirmDanger({ title: `Bloklash: ${u.name}`, consequences: ['Barcha sessiyalar darhol bekor qilinadi'], reasonMin: 5, okLabel: 'Bloklash', onConfirm: async ({ reason }) => { await app.api.post(`/api/v1/users/${u.id}/block`, { reason }); toast('Bloklandi', 'success'); reload(); refresh(); } }) })]);
    };
    await reload();
  }
  await refresh();
}

export async function renderRoles(main, params, app) {
  const box = h('div');
  main.append(pageHead('Rollar va ruxsatlar', "Tizim rollari o'zgartirilmaydi — nusxa yaratib moslashtiring"), box);
  await load(box, () => app.api.get('/api/v1/roles'), (r) => {
    const perms = Object.keys(r.permissions);
    const modules = [...new Set(perms.map((p) => p.split('.')[0]))];
    return [h('div', { class: 'table-wrap', style: { maxHeight: '70vh' } }, h('table', { class: 'data dense' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Ruxsat'), r.items.map((role) => h('th', { title: role.code }, role.name, role.mfa_required ? ' 🔐' : '', h('div', { class: 'caption' }, `${role.users} foyd.`))))),
      h('tbody', {}, modules.flatMap((mod) => [h('tr', {}, h('td', { colspan: r.items.length + 1, style: { background: 'var(--n-50)', fontWeight: 600 } }, mod)),
        ...perms.filter((p) => p.startsWith(`${mod}.`)).map((p) => h('tr', {}, h('td', { title: p }, r.permissions[p]), r.items.map((role) => h('td', { style: { textAlign: 'center' } }, role.permissions.includes(p) ? h('span', { style: { color: 'var(--c-success)' }, 'aria-label': 'bor' }, '✓') : h('span', { class: 'muted', 'aria-label': "yo'q" }, '·')))))])))),
    app.can('role.manage') ? h('div', { class: 'btn-bar', style: { marginTop: '12px' } }, btn('Maxsus rol yaratish', { onClick: () => customRole(r) })) : null];
  });
  function customRole(r) {
    const code = input({ placeholder: 'masalan: hr_viewer' }), name = input();
    const base = select(r.items.map((x) => [x.code, `${x.name} asosida`]));
    const checks = Object.entries(r.permissions).filter(([p]) => !['billing.manage', 'role.manage'].includes(p)).map(([p, label]) => { const c = checkbox(`${label} (${p})`); c.input.value = p; return c; });
    base.addEventListener('change', () => { const src = r.items.find((x) => x.code === base.value); checks.forEach((c) => { c.input.checked = src.permissions.includes(c.input.value); }); });
    const m = modal({ title: 'Maxsus rol', size: 'w960', body: [h('div', { class: 'form-grid' }, field({ label: 'Kod', input: code }), field({ label: 'Nomi', input: name }), field({ label: 'Nusxa olish', input: base })), h('div', { class: 'grid cols-2' }, checks)],
      footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn('Yaratish', { onClick: async () => { if (await act(() => app.api.post('/api/v1/roles', { code: code.value, name: name.value, permissions: checks.filter((c) => c.input.checked).map((c) => c.input.value) }), 'Rol yaratildi')) { m.close(); app.go('/security/roles'); } } })] });
  }
}

export async function renderSessions(main, params, app) {
  let tab = 'sessions';
  const tabBox = h('div'), box = h('div');
  main.append(pageHead('Sessiyalar va kirishlar'), tabBox, box);
  const st = { success: '', limit: 50, offset: 0 };
  async function refresh() {
    clear(tabBox).appendChild(tabs([{ key: 'sessions', label: 'Faol sessiyalar' }, { key: 'logins', label: 'Kirish tarixi' }], tab, (k) => { tab = k; refresh(); }));
    if (tab === 'sessions') await load(box, () => app.api.get('/api/v1/security/sessions'), (r) => table({ rows: r.items, columns: [
      { key: 'user_name', label: 'Foydalanuvchi' }, { key: 'login', label: 'Login' }, { key: 'ip', label: 'IP' }, { key: 'user_agent', label: 'Brauzer', wrap: true },
      { key: 'created_at', label: 'Boshlangan', render: (s) => fmtDateTime(s.created_at, app.tz) }, { key: 'mfa_passed', label: 'MFA', render: (s) => (s.mfa_passed ? '✓' : '—') },
      { key: 'x', label: '', render: (s) => (s.current ? badge('Joriy', 'info') : btn('Bekor qilish', { variant: 'danger-outline', size: 's', onClick: async () => { if (await act(() => app.api.post(`/api/v1/security/sessions/${s.id}/revoke`), 'Sessiya bekor qilindi (≤ 60 s)')) refresh(); } })) }] }));
    else {
      const sel = select([['', 'Hammasi'], ['1', 'Muvaffaqiyatli'], ['0', 'Muvaffaqiyatsiz']], { value: st.success });
      sel.addEventListener('change', () => { st.success = sel.value; st.offset = 0; refresh(); });
      await load(box, () => app.api.get('/api/v1/security/logins', { query: st }), (r) => [h('div', { class: 'filters' }, field({ label: 'Natija', input: sel })), table({ rows: r.items, columns: [
        { key: 'created_at', label: 'Vaqt', render: (l) => fmtDateTime(l.created_at, app.tz) }, { key: 'login', label: 'Login' }, { key: 'user_name', label: 'Foydalanuvchi' },
        { key: 'success', label: 'Natija', render: (l) => (l.success ? badge('OK', 'success') : badge(l.reason || 'xato', 'danger')) }, { key: 'ip', label: 'IP' }, { key: 'user_agent', label: 'Brauzer', wrap: true }] }),
      pagination({ total: r.total, limit: st.limit, offset: st.offset, onChange: (p) => { Object.assign(st, p); refresh(); } })]);
    }
  }
  await refresh();
}

export async function renderAudit(main, params, app) {
  const st = { action: '', object_type: '', from: '', to: '', limit: 50, offset: 0 };
  const box = h('div'), chainBox = h('div');
  const f = { action: input({ placeholder: 'masalan: employee.*' }), object_type: input({ placeholder: 'employee, device…' }), from: input({ type: 'date' }), to: input({ type: 'date' }) };
  Object.entries(f).forEach(([k, el]) => el.addEventListener('change', () => { st[k] = el.value; st.offset = 0; refresh(); }));
  main.append(pageHead('Audit log', "Hash-zanjirli, faqat qo'shiladigan jurnal", [
    btn('Butunlikni tekshirish', { variant: 'secondary', onClick: async () => {
      try { const r = await app.api.post('/api/v1/audit/verify', {}, { idempotent: false });
        clear(chainBox).appendChild(r.ok ? h('div', { class: 'note success' }, `✓ Zanjir butun: ${r.records.toLocaleString('ru-RU')} yozuv`) : h('div', { class: 'note danger' }, `✕ Buzilish aniqlandi: yozuv #${r.broken_at_seq}. Kritik ogohlantirish yaratildi.`)); }
      catch (e) { showError(e); }
    } }),
    app.can('audit.export') ? btn('CSV eksport', { variant: 'secondary', onClick: () => app.api.download(`/api/v1/audit/export?${new URLSearchParams(Object.fromEntries(Object.entries(st).filter(([k, v]) => v && !['limit', 'offset'].includes(k))))}`, 'fras-audit.csv').catch(showError) }) : null]),
  chainBox, h('div', { class: 'filters' }, field({ label: 'Amal', input: f.action }), field({ label: 'Obyekt turi', input: f.object_type }), field({ label: 'Dan', input: f.from }), field({ label: 'Gacha', input: f.to })), box);
  async function refresh() {
    await load(box, () => app.api.get('/api/v1/audit', { query: st }), (r) => [table({ rows: r.items, onRow: (a) => drawer({ title: `Audit #${a.seq}`, size: 'w720', body: [
      kv([['Vaqt', fmtDateTime(a.created_at, app.tz)], ['Aktor', `${a.actor_type} · ${a.actor_name || a.actor_id || '—'}`], ['Amal', a.action], ['Obyekt', `${a.object_type || '—'} ${a.object_id || ''}`], ['IP', a.ip], ['So\'rov ID', a.request_id], ['Natija', a.result], ['Hash', h('span', { class: 'mono' }, a.hash)]]),
      h('div', { class: 'diff' }, h('div', {}, h('strong', {}, 'Oldin'), h('pre', {}, prettify(a.before_json))), h('div', {}, h('strong', {}, 'Keyin'), h('pre', {}, prettify(a.after_json))))] }), columns: [
      { key: 'seq', label: '#', num: true }, { key: 'created_at', label: 'Vaqt', render: (a) => fmtDateTime(a.created_at, app.tz) }, { key: 'actor_name', label: 'Aktor', render: (a) => a.actor_name || a.actor_type },
      { key: 'action', label: 'Amal', render: (a) => h('span', { class: 'mono' }, a.action) }, { key: 'object_type', label: 'Obyekt' }, { key: 'ip', label: 'IP' }, { key: 'result', label: 'Natija' }] }),
    pagination({ total: r.total, limit: st.limit, offset: st.offset, onChange: (p) => { Object.assign(st, p); refresh(); } })]);
  }
  await refresh();
}
const prettify = (j) => { if (!j) return '—'; try { return JSON.stringify(JSON.parse(j), null, 2); } catch { return j; } };

export async function renderAlerts(main, params, app) {
  const st = { status: 'new', limit: 50, offset: 0 };
  const tabBox = h('div'), box = h('div');
  main.append(pageHead('Xavfsizlik ogohlantirishlari'), tabBox, box);
  async function refresh() {
    await load(box, () => app.api.get('/api/v1/security/alerts', { query: st }), (r) => {
      clear(tabBox).appendChild(tabs([{ key: 'new', label: 'Yangi', count: r.counts.new }, { key: 'in_review', label: "Ko'rib chiqilmoqda", count: r.counts.in_review }, { key: 'closed', label: 'Yopilgan', count: r.counts.closed }], st.status, (k) => { st.status = k; refresh(); }));
      return [table({ rows: r.items, onRow: open, rowClass: (a) => (['high', 'critical'].includes(a.severity) ? 'flag-danger' : ''), empty: emptyState({ icon: '✓', title: "Ogohlantirishlar yo'q" }), columns: [
        { key: 'severity', label: 'Jiddiylik', render: (a) => statusBadge(a.severity) }, { key: 'title', label: 'Turi' }, { key: 'device_name', label: 'Qurilma' },
        { key: 'created_at', label: 'Vaqt', render: (a) => fmtDateTime(a.created_at, app.tz) }, { key: 'assignee_name', label: "Mas'ul" }, { key: 'status', label: 'Holat', render: (a) => statusBadge(a.status) }] }),
      pagination({ total: r.total, limit: st.limit, offset: st.offset, onChange: (p) => { Object.assign(st, p); refresh(); } })];
    });
  }
  function open(a) {
    const res = textarea({ rows: 3, placeholder: 'Xulosa (yopish uchun kamida 10 belgi)' });
    const d = drawer({ title: a.title, body: [kv([['Jiddiylik', statusBadge(a.severity)], ['Holat', statusBadge(a.status)], ['Vaqt', fmtDateTime(a.created_at, app.tz)], ['Qurilma', a.device_name], ['Hodisa', a.event_id ? h('a', { href: `/app/attendance/events?tab=suspicious`, 'data-link': '' }, a.event_id) : '—']]),
      h('pre', { class: 'mono' }, JSON.stringify(a.details, null, 2)), a.resolution ? h('div', { class: 'note' }, a.resolution) : null, app.can('alert.manage') && a.status !== 'closed' ? field({ label: 'Xulosa', input: res }) : null],
    footer: app.can('alert.manage') && a.status !== 'closed' ? [
      a.status === 'new' ? btn("Ko'rib chiqishni boshlash", { variant: 'secondary', onClick: async () => { if (await act(() => app.api.patch(`/api/v1/security/alerts/${a.id}`, { status: 'in_review', version_updated_at: a.updated_at }), 'Sizga biriktirildi')) { d.close(); refresh(); } } }) : null,
      btn('Yopish', { onClick: async () => { if (res.value.trim().length < 10) { toast('Xulosa kamida 10 belgi', 'warning'); return; } if (await act(() => app.api.patch(`/api/v1/security/alerts/${a.id}`, { status: 'closed', resolution: res.value.trim(), version_updated_at: a.updated_at }), 'Yopildi')) { d.close(); refresh(); } } })] : [] });
  }
  await refresh();
}
