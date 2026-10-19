// SCR-80 … SCR-87 settings, plus billing, support, integrations, backups.
import { h, clear, btn, select, input, field, form, table, modal, toast, statusBadge, badge, emptyState, load, kv, confirmDanger, showError, textarea, checkbox, errorState } from '/assets/core/ui.js';
import { fmtDate, fmtDateTime, fmtMoney } from '/assets/core/format.js';
import { pageHead, orgTree, invalidateOrg, act } from './common.js';

const SECTIONS = [
  ['org', 'Tashkiliy tuzilma', 'org.read'], ['attendance_rules', 'Davomat qoidalari', 'settings.read'], ['biometric_policy', 'Biometrik siyosat', 'settings.read'],
  ['retention', 'Saqlash muddatlari', 'settings.read'], ['notifications', 'Bildirishnomalar', 'settings.read'], ['locale', 'Til va vaqt', 'settings.read'],
  ['integrations', 'Integratsiyalar va API', 'integration.manage'], ['backup', 'Backup va eksport', 'settings.read'], ['billing', 'Obuna va to\'lovlar', 'billing.read'], ['support', 'Texnik yordam', 'settings.read'],
];

export async function render(main, params, app) {
  const section = params.section || 'org';
  const nav = h('nav', { class: 'card', style: { padding: '8px', alignSelf: 'start' } }, SECTIONS.filter(([, , p]) => app.can(p)).map(([k, l]) => h('a', { class: `nav ${k === section ? 'active' : ''}`, href: `/app/settings/${k}`, 'data-link': '', style: { display: 'block', padding: '8px 10px', borderRadius: '6px', background: k === section ? 'var(--c-primary-soft)' : '', fontWeight: k === section ? 600 : 400 } }, l)));
  const body = h('div', { style: { minWidth: 0 } });
  main.append(pageHead('Sozlamalar'), h('div', { style: { display: 'grid', gridTemplateColumns: '240px 1fr', gap: '16px' }, class: 'profile-grid' }, nav, body));
  const fn = { org: orgSection, attendance_rules: rulesSection, biometric_policy: bioSection, retention: retentionSection, notifications: notifSection, locale: localeSection, integrations: integrationsSection, backup: backupSection, billing: billingSection, support: supportSection }[section];
  if (fn) await fn(body, app); else body.appendChild(emptyState({ title: "Bo'lim topilmadi" }));
}

async function versionHeader(app, key, box) {
  const r = await app.api.get(`/api/v1/settings/${key}`);
  box.appendChild(h('div', { class: 'row caption', style: { marginBottom: '8px' } }, r.version ? `Joriy versiya v${r.version.version} · ${fmtDateTime(r.version.created_at, app.tz)}` : "Standart qiymatlar (o'zgartirilmagan)",
    btn('Tarix', { variant: 'tertiary', size: 's', onClick: async () => { const hst = await app.api.get(`/api/v1/settings/${key}/history`); modal({ title: 'Versiyalar tarixi', size: 'w960', body: table({ rows: hst.items, columns: [{ key: 'version', label: 'v' }, { key: 'created_at', label: 'Vaqt', render: (x) => fmtDateTime(x.created_at, app.tz) }, { key: 'value', label: 'Qiymat', wrap: true, render: (x) => h('span', { class: 'mono' }, JSON.stringify(x.value)) }] }) }); } })));
  return r;
}

// ---------------------------------------------------------------- org tree (SCR-80)
async function orgSection(box, app) {
  const draw = async () => {
    invalidateOrg();
    clear(box);
    let tree; try { tree = await orgTree(app, true); } catch (e) { box.appendChild(errorState(e)); return; }
    const manage = app.can('org.manage');
    const addBtn = (label, fn) => (manage ? btn(label, { variant: 'tertiary', size: 's', onClick: fn }) : null);
    const ask = (title, fields, url, extra = {}) => {
      const f = form(fields);
      const m = modal({ title, body: f.el, footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn('Saqlash', { onClick: async () => { if (!f.validate()) return; if (await act(() => app.api.post(url, { ...f.values(), ...extra }), 'Saqlandi', f)) { m.close(); draw(); } } })] });
    };
    box.append(h('div', { class: 'card tree' }, h('div', { class: 'row' }, h('h3', { style: { flex: 1, margin: 0 } }, 'Tashkilot'),
      addBtn("+ Zavod", () => ask('Yangi zavod', [{ name: 'code', label: 'Kod', required: true }, { name: 'name', label: 'Nomi', required: true }, { name: 'timezone', label: 'Vaqt zonasi', value: 'Asia/Tashkent' }, { name: 'address', label: 'Manzil' }], '/api/v1/org/sites')),
      addBtn('+ Lavozim', () => ask('Yangi lavozim', [{ name: 'name', label: 'Nomi', required: true }], '/api/v1/org/positions'))),
    h('ul', {}, tree.sites.map((s) => h('li', {}, h('span', { class: 'node' }, '🏭 ', h('strong', {}, s.name), h('span', { class: 'caption' }, ` · ${s.code} · ${s.timezone}`)),
      addBtn('+ Bino', () => ask(`${s.name}: bino`, [{ name: 'name', label: 'Nomi', required: true }], '/api/v1/org/buildings', { site_id: s.id })),
      addBtn('+ Darvoza', () => ask(`${s.name}: kirish nuqtasi`, [{ name: 'name', label: 'Nomi', required: true }, { name: 'direction', label: "Yo'nalish", type: 'select', options: [['both', 'Ikkalasi'], ['in', 'Kirish'], ['out', 'Chiqish']] }], '/api/v1/org/access-points', { site_id: s.id })),
      addBtn("+ Bo'lim", () => ask(`${s.name}: bo'lim`, [{ name: 'code', label: 'Kod', required: true }, { name: 'name', label: 'Nomi', required: true }, { name: 'parent_id', label: "Yuqori bo'lim", type: 'select', options: [['', '—'], ...s.departments.map((d) => [d.id, d.name])] }], '/api/v1/org/departments', { site_id: s.id })),
      h('ul', {},
        s.buildings.map((b) => h('li', {}, h('span', { class: 'node' }, '🏢 ', b.name), addBtn('+ Zona', () => ask(`${b.name}: zona`, [{ name: 'name', label: 'Nomi', required: true }], '/api/v1/org/zones', { building_id: b.id })),
          h('ul', {}, b.zones.map((z) => h('li', {}, h('span', { class: 'node' }, '▫ ', z.name)))))),
        s.access_points.map((a) => h('li', {}, h('span', { class: 'node' }, '🚪 ', a.name, h('span', { class: 'caption' }, ` · ${a.direction}`)))),
        s.departments.map((d) => h('li', {}, h('span', { class: 'node' }, '👥 ', d.name, h('span', { class: 'caption' }, ` · ${d.code} · ${d.employees} xodim`), d.status !== 'active' ? badge('arxiv') : null),
          manage && d.status === 'active' ? btn('Arxivlash', { variant: 'tertiary', size: 's', onClick: async () => { try { await app.api.post(`/api/v1/org/departments/${d.id}/archive`); draw(); } catch (e) { toast(e.code === 'DEPARTMENT_NOT_EMPTY' ? `Bo'limda ${e.details.employees} faol xodim bor — avval ko'chiring` : e.message, 'error'); } } }) : null))))))));
  };
  await draw();
}

// ---------------------------------------------------------------- rules + simulator (SCR-82)
async function rulesSection(box, app) {
  const cur = await versionHeader(app, 'attendance_rules', box);
  const v = cur.value;
  const f = form([{ name: 'debounce_min', label: 'Takroriy hodisa oynasi (daq)', type: 'number', min: 0, max: 30, help: 'Bir xodim, bir yo\'nalish, N daqiqa ichida — takroriy' },
    { name: 'missing_out_after_min', label: 'Chiqish qayd etilmasa anomaliya (smena tugagach, daq)', type: 'number', min: 0, max: 720 },
    { name: 'anti_passback', label: 'Anti-passback', type: 'select', options: [['off', "O'chirilgan"], ['soft', 'Ogohlantirish'], ['hard', 'Bloklash']] },
    { name: 'min_rest_hours', label: 'Smenalar orasida minimal dam (soat)', type: 'number', min: 0, max: 24 },
    { name: 'overtime_requires_approval', label: "Qo'shimcha ish tasdiq talab qiladi", type: 'checkbox' }, { name: 'late_event_review', label: "Yopilgan davrga kech kelgan hodisalarni HR navbatiga yuborish", type: 'checkbox' }], v);
  const simBox = h('div');
  box.append(h('div', { class: 'card stack', style: { borderColor: 'var(--c-warning)' } }, h('div', { class: 'note warning' }, "Bu o'zgarish davomat hisobiga ta'sir qiladi. Saqlashdan oldin simulyatorni ishga tushiring."), f.el,
    h('div', { class: 'btn-bar' }, btn("O'tgan 30 kunda sinash", { variant: 'secondary', onClick: async () => {
      const vals = f.values();
      await (async () => { try { const r = await app.api.post('/api/v1/settings/attendance_rules/simulate', { value: vals, days: 30 }, { idempotent: false });
        clear(simBox).append(table({ dense: true, rows: [['Kechikishlar (kun)', 'late'], ["Qo'shimcha ish (soat)", 'overtime_min'], ['Ishlangan (soat)', 'worked_min'], ['Anomaliyali kunlar', 'incomplete']].map(([l, k], i) => ({ id: i, l, k })), columns: [
          { key: 'l', label: "Ko'rsatkich" }, { key: 'cur', label: 'Joriy', num: true, render: (x) => fmt(r.current[x.k], x.k) }, { key: 'new', label: 'Taklif', num: true, render: (x) => fmt(r.proposed[x.k], x.k) }] }), h('div', { class: 'caption' }, `${r.employees} xodim, ${r.from} – ${r.to}. ${r.note}`)); }
      catch (e) { showError(e); } })();
    } }), app.can('settings.attendance_rules') ? btn('Saqlash', { onClick: async () => { if (await act(() => app.api.put('/api/v1/settings/attendance_rules', { value: f.values() }), "Saqlandi. Qoida keyingi hisob-kitoblarga qo'llanadi.", f)) { clear(box); rulesSection(box, app); } } }) : null), simBox));
  const fmt = (val, k) => (k.endsWith('_min') ? (val / 60).toFixed(1) : val);
}

async function bioSection(box, app) {
  const cur = await versionHeader(app, 'biometric_policy', box);
  const v = cur.value;
  const prof = select([['strict', 'Qat\'iy'], ['standard', 'Standart'], ['lenient', 'Yumshoq']], { value: v.profile });
  const live = checkbox('Liveness majburiy'); live.input.checked = v.liveness_required;
  const border = select([['retry', 'Qayta urinish'], ['alternative', 'Muqobil usul'], ['guard', "Qo'riqchi"]], { value: v.border_action });
  const mask = checkbox('Niqob rejimi'); mask.input.checked = v.mask_mode;
  const approver = input({ placeholder: 'Ikkinchi tasdiqlovchi (xavfsizlik xodimi) foydalanuvchi ID' });
  box.append(h('div', { class: 'card stack' }, h('div', { class: 'note warning' }, "Chegaralar PoC'da o'z ma'lumotlaringizda kalibrlanmaguncha taxminiy. Pasaytirish noto'g'ri qabul ehtimolini oshiradi va ikki kishi tasdig'ini talab qiladi."),
    table({ dense: true, rows: Object.entries(v.thresholds).map(([k, t]) => ({ id: k, k, ...t })), columns: [{ key: 'k', label: 'Profil' }, { key: 'accept', label: 'T_accept', num: true }, { key: 'review', label: 'T_review', num: true }] }),
    h('div', { class: 'form-grid' }, field({ label: 'Faol profil', input: prof }), field({ label: 'Chegara zonasida', input: border }), live, mask, field({ label: 'Ikkinchi tasdiqlovchi', input: approver, help: 'Faqat siyosat yumshatilganda kerak' })),
    kv([['Dublikat chegarasi', v.duplicate_threshold], ['Minimal kadrlar', v.min_frames], ['Minimal sifat', v.min_quality], ['Rozilik siyosati versiyasi', v.consent_policy_version]]),
    app.can('settings.biometric_policy') ? h('div', { class: 'btn-bar' }, btn('Saqlash', { onClick: async () => {
      try { await app.api.put('/api/v1/settings/biometric_policy', { value: { profile: prof.value, liveness_required: live.input.checked, border_action: border.value, mask_mode: mask.input.checked } }, { headers: approver.value ? { 'X-Second-Approver': approver.value } : {} }); toast('Saqlandi. Terminallarga galereya bilan yetkaziladi.', 'success'); }
      catch (e) { toast(e.code === 'SECOND_APPROVAL_REQUIRED' ? "Siyosatni yumshatish uchun xavfsizlik xodimi ID'sini kiriting" : e.message, 'error'); }
    } })) : null));
}

async function retentionSection(box, app) {
  const cur = await versionHeader(app, 'retention', box);
  const f = form([{ name: 'events_days', label: 'Davomat hodisalari (kun)', type: 'number', help: 'Qonuniy minimum: 1825' }, { name: 'capture_days', label: 'Shubhali kadrlar (kun, ≤ 90)', type: 'number' },
    { name: 'enrollment_images_days', label: 'Enrollment suratlari (kun)', type: 'number', help: '0 — darhol o\'chiriladi (tavsiya)' }, { name: 'template_after_termination_days', label: "Ishdan bo'shagandan keyin shablon (kun)", type: 'number' },
    { name: 'audit_days', label: 'Audit log (kun)', type: 'number' }, { name: 'logs_days', label: 'Texnik loglar (kun)', type: 'number' }, { name: 'exports_days', label: 'Eksport fayllari (kun)', type: 'number' }], cur.value);
  box.append(h('div', { class: 'card stack' }, f.el, app.can('settings.retention') ? h('div', { class: 'btn-bar' }, btn('Saqlash', { onClick: async () => {
    try { await app.api.put('/api/v1/settings/retention', { value: f.values() }); toast('Saqlandi', 'success'); }
    catch (e) { if (e.code === 'RETENTION_BELOW_FLOOR') toast(`Qonuniy minimumdan past bo'lmaydi: ${e.details.minimum} kun`, 'error'); else showError(e, f); }
  } })) : null, h('div', { class: 'caption' }, "O'chirish ishi har kuni bajariladi; hisoboti audit logda.")));
}

async function notifSection(box, app) {
  const cur = await versionHeader(app, 'notifications', box);
  const v = cur.value;
  const absent = input({ type: 'number', value: v.absent_after_min });
  const ch = Object.fromEntries(['in_app', 'email', 'telegram'].map((k) => { const c = checkbox({ in_app: 'Ilova ichida', email: 'Email', telegram: 'Telegram' }[k]); c.input.checked = v.channels[k]; return [k, c]; }));
  const qf = input({ type: 'time', value: v.quiet_hours.from }), qt = input({ type: 'time', value: v.quiet_hours.to });
  box.append(h('div', { class: 'card stack' }, field({ label: "Kelmaganlar haqida xabar (smena boshidan keyin, daq)", input: absent }), h('div', { class: 'row' }, Object.values(ch)),
    h('div', { class: 'form-grid' }, field({ label: 'Sokin soatlar dan', input: qf }), field({ label: 'gacha', input: qt })), h('div', { class: 'caption' }, "Xodimlarga yuboriladigan xabarlarda biometrik ma'lumot bo'lmaydi."),
    app.can('settings.notifications') ? h('div', { class: 'btn-bar' }, btn('Saqlash', { onClick: () => act(() => app.api.put('/api/v1/settings/notifications', { value: { absent_after_min: Number(absent.value), channels: Object.fromEntries(Object.entries(ch).map(([k, c]) => [k, c.input.checked])), quiet_hours: { from: qf.value, to: qt.value } } }), 'Saqlandi') })) : null));
}

async function localeSection(box, app) {
  const cur = await versionHeader(app, 'locale', box);
  const lang = select([['uz', "O'zbek"], ['ru', 'Русский'], ['en', 'English']], { value: cur.value.default_language });
  box.append(h('div', { class: 'card stack' }, field({ label: 'Standart til', input: lang }), kv([['Sana formati', cur.value.date_format], ['Hafta boshi', 'Dushanba'], ['Vaqt zonasi', 'Har zavod uchun alohida (Tashkiliy tuzilma)']]),
    app.can('org.manage') ? h('div', { class: 'btn-bar' }, btn('Saqlash', { onClick: () => act(() => app.api.put('/api/v1/settings/locale', { value: { default_language: lang.value } }), 'Saqlandi') })) : null));
}

async function integrationsSection(box, app) {
  const keysBox = h('div'), hooksBox = h('div');
  box.append(h('div', { class: 'card stack' }, h('h3', {}, 'API kalitlari', h('span', { class: 'right' }, btn('Kalit yaratish', { size: 's', onClick: () => newKey() }))), keysBox),
    h('div', { class: 'card stack', style: { marginTop: '16px' } }, h('h3', {}, 'Webhooklar', h('span', { class: 'right' }, btn("Webhook qo'shish", { size: 's', onClick: () => newHook() }))), hooksBox),
    h('div', { class: 'card stack', style: { marginTop: '16px' } }, h('h3', {}, 'Payroll / 1C'), h('p', { class: 'muted' }, "Davr yopilgach Davrlar sahifasidan \"Payroll eksport\" (CSV: personnel_no, hours_worked, overtime_hours …) yoki REST API: GET /api/v1/attendance/daily-summaries (X-Api-Key)."),
      h('h3', {}, 'SSO (OIDC/SAML)'), h('p', { class: 'muted' }, 'Enterprise tarifida korxona IdP bilan sozlanadi.')));
  const refresh = async () => {
    await load(keysBox, () => app.api.get('/api/v1/integrations/api-keys'), (r) => table({ dense: true, rows: r.items, empty: emptyState({ title: "Kalitlar yo'q" }), columns: [
      { key: 'name', label: 'Nomi' }, { key: 'prefix', label: 'Prefiks', render: (k) => h('span', { class: 'mono' }, `fras_${k.prefix}_…`) }, { key: 'scopes', label: 'Huquqlar', render: (k) => k.scopes.join(', ') },
      { key: 'last_used_at', label: 'Oxirgi foydalanish', render: (k) => fmtDateTime(k.last_used_at, app.tz) }, { key: 'state', label: 'Holat', render: (k) => (k.revoked_at ? statusBadge('revoked') : k.rotation_due ? badge('Rotatsiya vaqti', 'warning') : statusBadge('active')) },
      { key: 'x', label: '', render: (k) => (k.revoked_at ? '' : btn('Bekor qilish', { variant: 'danger-outline', size: 's', onClick: async () => { if (await act(() => app.api.post(`/api/v1/integrations/api-keys/${k.id}/revoke`), 'Bekor qilindi')) refresh(); } })) }] }));
    await load(hooksBox, () => app.api.get('/api/v1/integrations/webhooks'), (r) => table({ dense: true, rows: r.items.filter((x) => x.status === 'active'), empty: emptyState({ title: "Webhooklar yo'q" }), columns: [
      { key: 'url', label: 'URL', wrap: true }, { key: 'events', label: 'Hodisalar', render: (x) => x.events.join(', ') }, { key: 'recent', label: 'Oxirgi yetkazish', render: (x) => (x.recent[0] ? statusBadge(x.recent[0].status) : '—') },
      { key: 'x', label: '', render: (x) => h('span', { class: 'row' }, btn('Test', { variant: 'tertiary', size: 's', onClick: () => act(() => app.api.post(`/api/v1/integrations/webhooks/${x.id}/test`), 'Test navbatga qo\'yildi') }), btn("O'chirish", { variant: 'danger-outline', size: 's', onClick: async () => { if (await act(() => app.api.del(`/api/v1/integrations/webhooks/${x.id}`))) refresh(); } })) }] }));
  };
  function newKey() {
    const name = input(); const scopes = ['attendance.read', 'employee.read', 'report.view', 'org.read'].map((s) => { const c = checkbox(s); c.input.value = s; return c; });
    const ips = input({ placeholder: '10.0.0.5, 10.0.0.6 (ixtiyoriy)' }); const exp = input({ type: 'date' });
    const m = modal({ title: 'API kaliti', body: [field({ label: 'Nomi', input: name }), h('div', { class: 'row' }, scopes), field({ label: 'IP allowlist', input: ips }), field({ label: 'Amal qilish muddati', input: exp })],
      footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn('Yaratish', { onClick: async () => {
        try { const r = await app.api.post('/api/v1/integrations/api-keys', { name: name.value, scopes: scopes.filter((c) => c.input.checked).map((c) => c.input.value), ip_allowlist: ips.value.split(',').map((x) => x.trim()).filter(Boolean), expires_on: exp.value || null });
          m.close(); refresh(); modal({ title: 'Kalit (faqat bir marta ko\'rsatiladi)', body: [h('input', { class: 'input mono', readonly: true, value: r.key, onclick: (e) => e.target.select() }), h('div', { class: 'note warning' }, 'Kalitni xavfsiz joyda saqlang. Qayta ko\'rsatilmaydi.')] }); }
        catch (e) { toast(e.code === 'PLAN_FEATURE' ? 'REST API Professional tarifidan mavjud' : e.message, 'error'); }
      } })] });
  }
  function newHook() {
    const url = input({ placeholder: 'https://…' }); const evs = ['attendance.event', 'attendance.summary', 'employee.created', 'employee.deactivated', 'period.closed'].map((s) => { const c = checkbox(s); c.input.value = s; return c; });
    const m = modal({ title: 'Webhook', body: [field({ label: 'URL (HTTPS)', input: url }), h('div', { class: 'stack' }, evs)], footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn('Yaratish', { onClick: async () => {
      try { const r = await app.api.post('/api/v1/integrations/webhooks', { url: url.value, events: evs.filter((c) => c.input.checked).map((c) => c.input.value) }); m.close(); refresh();
        modal({ title: 'Imzo kaliti', body: [h('input', { class: 'input mono', readonly: true, value: r.signing_secret }), h('div', { class: 'caption' }, r.note)] }); }
      catch (e) { showError(e); }
    } })] });
  }
  await refresh();
}

async function backupSection(box, app) {
  const list = h('div');
  box.append(h('div', { class: 'card stack' }, h('h3', {}, "To'liq ma'lumot eksporti"), h('p', { class: 'muted' }, "Barcha jadvallar CSV ko'rinishida (biometrik shablonlar, parol xeshlari va qurilma kalitlari kiritilmaydi). Istalgan vaqtda, obuna holatidan qat'i nazar."),
    h('div', { class: 'btn-bar' }, btn('ZIP yuklab olish', { variant: 'secondary', onClick: () => app.api.download('/api/v1/system/full-export', 'fras-full-export.zip', { method: 'POST', body: {} }).catch(showError) }))));
  if (app.can('backup.manage')) {
    box.append(h('div', { class: 'card stack', style: { marginTop: '16px' } }, h('h3', {}, 'Backup', h('span', { class: 'right' }, btn('Hozir backup', { size: 's', onClick: async () => { if (await act(() => app.api.post('/api/v1/system/backups'), 'Backup yaratildi')) refresh(); } }))), list));
    const refresh = () => load(list, () => app.api.get('/api/v1/system/backups'), (r) => [kv(Object.entries(r.policy)), table({ dense: true, rows: r.items, columns: [
      { key: 'created_at', label: 'Vaqt', render: (b) => fmtDateTime(b.created_at, app.tz) }, { key: 'kind', label: 'Turi' }, { key: 'size_bytes', label: 'Hajm', num: true, render: (b) => `${(b.size_bytes / 1048576).toFixed(2)} MB` },
      { key: 'status', label: 'Holat', render: (b) => statusBadge(b.status === 'ok' ? 'acked' : 'failed') },
      { key: 'x', label: '', render: (b) => (b.kind === 'backup' ? btn('Tiklash testi', { variant: 'tertiary', size: 's', onClick: async () => { const r2 = await act(() => app.api.post(`/api/v1/system/backups/${b.id}/restore-test`)); if (r2) toast(r2.ok ? `✓ Butun: ${r2.events} hodisa, integrity ${r2.integrity}` : '✕ Tiklash testi muvaffaqiyatsiz', r2.ok ? 'success' : 'error'); refresh(); } }) : '') }] })]);
    await refresh();
  }
}

async function billingSection(box, app) {
  await load(box, () => app.api.get('/api/v1/billing'), (r) => {
    const s = r.subscription;
    return [h('div', { class: 'note' }, r.guarantee), h('div', { class: 'grid cols-2', style: { marginTop: '12px' } },
      h('div', { class: 'card' }, h('h3', {}, 'Obuna'), kv([['Tarif', r.plan.name], ['Holat', statusBadge(s.status)], ['Hisob davri', s.billing_cycle === 'annual' ? 'Yillik' : 'Oylik'], ['Davr', `${fmtDate(s.period_start, app.tz)} – ${fmtDate(s.period_end, app.tz)}`],
        s.trial_ends_at ? ['Sinov tugaydi', fmtDate(s.trial_ends_at, app.tz)] : null, s.cancel_at ? ['Bekor qilinadi', fmtDate(s.cancel_at, app.tz)] : null, ['Oylik qiymat', fmtMoney(r.mrr_cents)]])),
      h('div', { class: 'card' }, h('h3', {}, 'Foydalanish'), kv(Object.entries(r.usage).map(([k, v]) => [{ employees: 'Faol xodimlar', sites: 'Zavodlar', devices: 'Qurilmalar', admins: 'Adminlar' }[k], `${v} / ${r.plan.limits[k] ?? '∞'}`])))),
    h('h3', { style: { marginTop: '16px' } }, 'Hisob-fakturalar'), table({ dense: true, rows: r.invoices, empty: emptyState({ title: "Hisob-fakturalar yo'q" }), columns: [
      { key: 'number', label: '№' }, { key: 'period', label: 'Davr', render: (i) => `${fmtDate(i.period_start)} – ${fmtDate(i.period_end)}` }, { key: 'amount_cents', label: 'Summa', num: true, render: (i) => fmtMoney(i.amount_cents) },
      { key: 'status', label: 'Holat', render: (i) => statusBadge(i.status) }, { key: 'due_at', label: 'Muddat', render: (i) => fmtDate(i.due_at, app.tz) }] }),
    app.can('billing.manage') ? h('div', { class: 'card stack', style: { marginTop: '16px' } }, h('h3', {}, 'Tarifni o\'zgartirish'), h('div', { class: 'grid cols-3' }, r.plans.filter((p) => p.code !== 'enterprise').map((p) => h('div', { class: 'card' }, h('strong', {}, p.name), h('div', { class: 'caption' }, p.price_model === 'flat' ? `${fmtMoney(p.price_cents)}/oy` : `${fmtMoney(p.price_cents)} / xodim / oy, min ${fmtMoney(p.min_monthly_cents)}`),
      h('div', { class: 'caption' }, `${p.limits.employees ?? '∞'} xodim · ${p.limits.devices ?? '∞'} qurilma`),
      p.code === r.plan.code ? badge('Joriy', 'primary') : btn('Tanlash', { variant: 'secondary', size: 's', onClick: async () => { try { await app.api.post('/api/v1/billing/change-plan', { plan_code: p.code }); toast('Tarif o\'zgartirildi', 'success'); app.go('/settings/billing'); } catch (e) { toast(e.code === 'PLAN_DOWNGRADE_BLOCKED' ? `Joriy foydalanish yangi tarif limitidan oshadi: ${Object.keys(e.details.over).join(', ')}` : e.message, 'error'); } } })))),
      h('div', { class: 'btn-bar' }, s.status !== 'cancelled' ? btn('Obunani bekor qilish', { variant: 'danger-outline', onClick: () => cancelSub() }) : null)) : null];
  });
  function cancelSub() {
    const reason = select([['price', 'Narx'], ['missing_feature', "Kerakli funksiya yo'q"], ['quality', 'Sifat'], ['company_closed', 'Korxona yopildi'], ['other_system', 'Boshqa tizimga o\'tdik'], ['other', 'Boshqa']]);
    confirmDanger({ title: 'Obunani bekor qilish', consequences: ['Obuna joriy davr oxirigacha ishlaydi', "Ma'lumotlar 90 kun saqlanadi, to'liq eksport ochiq", 'Mutaxassis bilan suhbat ixtiyoriy'],
      extra: field({ label: 'Sabab', input: reason }), reasonMin: 0, okLabel: 'Bekor qilish', onConfirm: async ({ reason: comment }) => { const r = await app.api.post('/api/v1/billing/cancel', { reason: reason.value, comment: comment || null }); toast(r.note, 'info'); app.go('/settings/billing'); } });
  }
}

async function supportSection(box, app) {
  const list = h('div');
  const f = form([{ name: 'subject', label: 'Mavzu', required: true, minlength: 5 }, { name: 'priority', label: 'Ustuvorlik', type: 'select', options: [['normal', 'Oddiy'], ['low', 'Past'], ['high', 'Yuqori'], ['critical', 'Kritik (darvoza ishlamayapti)']] },
    { name: 'body', label: 'Tavsif', type: 'textarea', required: true, minlength: 10, full: true }]);
  box.append(h('div', { class: 'card stack' }, h('h3', {}, 'Murojaat yuborish'), f.el, h('div', { class: 'btn-bar' }, btn('Yuborish', { onClick: async () => { if (!f.validate()) return; if (await act(() => app.api.post('/api/v1/support/tickets', f.values()), 'Murojaat qabul qilindi', f)) { Object.keys(f.fields).forEach((k) => f.set(k, k === 'priority' ? 'normal' : '')); refresh(); } } }))),
    h('div', { class: 'card', style: { marginTop: '16px' } }, h('h3', {}, 'Murojaatlarim'), list),
    h('div', { class: 'card stack', style: { marginTop: '16px' } }, h('h3', {}, 'Fikr-mulohaza'), feedbackBlock(app)));
  const refresh = () => load(list, () => app.api.get('/api/v1/support/tickets'), (r) => table({ dense: true, rows: r.items, empty: emptyState({ title: "Murojaatlar yo'q" }), columns: [
    { key: 'created_at', label: 'Vaqt', render: (t) => fmtDateTime(t.created_at, app.tz) }, { key: 'subject', label: 'Mavzu' }, { key: 'priority', label: 'Ustuvorlik' }, { key: 'status', label: 'Holat', render: (t) => statusBadge(t.status === 'open' ? 'open' : t.status) },
    { key: 'sla_due_at', label: 'Javob muddati', render: (t) => fmtDateTime(t.sla_due_at, app.tz) }] }));
  await refresh();
}

function feedbackBlock(app) {
  const score = select(Array.from({ length: 11 }, (_, i) => [i, i]), { value: 8 });
  const comment = textarea({ rows: 2 });
  return h('div', { class: 'stack' }, field({ label: 'FRAS ni hamkasbingizga tavsiya qilish ehtimoli (0–10)', input: score }), field({ label: 'Izoh', input: comment }),
    h('div', { class: 'btn-bar' }, btn('Yuborish', { variant: 'secondary', onClick: () => act(() => app.api.post('/api/v1/feedback', { score: Number(score.value), comment: comment.value || null, context: 'settings' }), 'Rahmat!') })));
}
