// SCR-10 … SCR-15: employee list, form, profile, import, duplicates, deactivation.
import { h, clear, btn, select, input, field, form, table, pagination, tabs, modal, drawer, toast, statusBadge, badge, errorState, emptyState, load, kv, confirmDanger, checkbox, showError, menu, textarea } from '/assets/core/ui.js';
import { fmtDate, fmtDateTime, relTime, todayISO, initials, fmtDuration } from '/assets/core/format.js';
import { pageHead, orgTree, act } from './common.js';

const BIO = { active: ['Ro\'yxatdan o\'tgan', 'success'], none: ["Yo'q", ''], review: ['Tekshiruvda', 'warning'], revoked: ['Bekor qilingan', ''], declined: ['Rad etgan (karta/PIN)', 'info'] };
const bioBadge = (s) => badge(...(BIO[s] || [s, '']));

export async function renderList(main, params, app) {
  const q = app.query();
  const st = { tab: q.tab || 'active', q: q.q || '', department_id: q.department_id || '', position_id: '', team: '', biometric_status: '', sort: 'name', limit: 50, offset: 0 };
  const tree = await orgTree(app).catch(() => ({ sites: [], positions: [] }));
  const depts = tree.sites.flatMap((s) => s.departments);
  const selected = new Set();
  const tabBox = h('div'), bulkBox = h('div'), listBox = h('div'), count = h('span', { class: 'caption' });
  const f = {
    q: input({ type: 'search', value: st.q, placeholder: 'F.I.Sh., tabel №, telefon oxirgi 4 raqami' }),
    department_id: select([['', "Barcha bo'limlar"], ...depts.map((d) => [d.id, d.name])], { value: st.department_id }),
    position_id: select([['', 'Barcha lavozimlar'], ...tree.positions.map((p) => [p.id, p.name])]),
    team: select([['', 'Barcha brigadalar'], ...['A', 'B', 'C', 'D'].map((t) => [t, `Brigada ${t}`])]),
    biometric_status: select([['', 'Biometrika: hammasi'], ...Object.entries(BIO).map(([k, v]) => [k, v[0]])]),
  };
  let timer;
  f.q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { if (f.q.value.trim().length === 1) return; st.q = f.q.value.trim(); st.offset = 0; refresh(); }, 300); });
  for (const k of ['department_id', 'position_id', 'team', 'biometric_status']) f[k].addEventListener('change', () => { st[k] = f[k].value; st.offset = 0; refresh(); });
  const more = btn('', { variant: 'icon', icon: '⋯', title: "Ko'proq", onClick: () => menu(more, [
    app.can('employee.merge') ? { label: 'Takroriylar navbati', onClick: () => app.go('/employees/duplicates') } : null,
    app.can('employee.import') ? { label: 'Import shablonini yuklab olish', onClick: () => app.api.download('/api/v1/employees/import-template', 'fras-xodimlar-shablon.xlsx') } : null]) });
  main.append(pageHead('Xodimlar', count, [
    app.can('employee.write') ? btn("Xodim qo'shish", { icon: '+', onClick: () => app.go('/employees/new') }) : null,
    app.can('employee.import') ? btn('Import', { variant: 'secondary', onClick: () => app.go('/employees/import') }) : null,
    app.can('employee.export') ? btn('Eksport', { variant: 'secondary', onClick: () => exportModal(app) }) : null, more]),
  tabBox, h('div', { class: 'filters' }, h('div', { class: 'field grow' }, h('label', { for: 'emp-q' }, 'Qidirish'), Object.assign(f.q, { id: 'emp-q' })),
    field({ label: "Bo'lim", input: f.department_id }), field({ label: 'Lavozim', input: f.position_id }), field({ label: 'Brigada', input: f.team }), field({ label: 'Biometrika', input: f.biometric_status })),
  bulkBox, listBox);

  function bulkBar() {
    clear(bulkBox);
    if (!selected.size) return;
    const deptSel = select(depts.map((d) => [d.id, d.name]));
    bulkBox.appendChild(h('div', { class: 'bulk-bar', role: 'region', 'aria-label': 'Ommaviy amallar' }, h('strong', {}, `${selected.size} ta tanlandi`),
      app.can('shift.assign') ? btn('Smena biriktirish', { variant: 'secondary', size: 's', onClick: () => app.go(`/shifts/schedule?employees=${[...selected].join(',')}`) }) : null,
      app.can('employee.write') ? h('span', { class: 'row' }, deptSel, btn("Bo'limga ko'chirish", { variant: 'secondary', size: 's', onClick: async () => {
        const r = await act(() => app.api.post('/api/v1/employees/bulk', { ids: [...selected], action: 'move_department', department_id: deptSel.value }));
        if (r) { toast(`${r.done} ta ko'chirildi${r.skipped.length ? `, ${r.skipped.length} o'tkazib yuborildi` : ''}`, 'success'); selected.clear(); refresh(); } } })) : null,
      app.can('employee.write') ? btn('Enrollment taklifnomasi', { variant: 'secondary', size: 's', onClick: async () => { const r = await act(() => app.api.post('/api/v1/employees/bulk', { ids: [...selected], action: 'invite_enrollment' })); if (r) toast(`${r.done} ta xodimga bildirishnoma yuborildi`, 'success'); } }) : null,
      app.can('employee.deactivate') ? btn('Deaktivatsiya', { variant: 'danger-outline', size: 's', onClick: () => confirmDanger({ title: `${selected.size} ta xodimni deaktivatsiya qilish`,
        consequences: ['Terminallar galereyasidan 5 daqiqa ichida olib tashlanadi', 'Portal hisoblari bloklanadi', 'Biometrik profil siyosatga ko\'ra o\'chiriladi'], reasonMin: 0,
        okLabel: 'Deaktivatsiya', onConfirm: async () => { const r = await app.api.post('/api/v1/employees/bulk', { ids: [...selected], action: 'deactivate', reason: 'other' }); toast(`${r.done} ta deaktivatsiya qilindi`, 'success'); selected.clear(); refresh(); } }) }) : null,
      btn('Bekor qilish', { variant: 'tertiary', size: 's', onClick: () => { selected.clear(); refresh(); } })));
  }

  async function refresh() {
    app.setQuery({ tab: st.tab, q: st.q, department_id: st.department_id });
    await load(listBox, () => app.api.get('/api/v1/employees', { query: st }), (r) => {
      count.textContent = `${r.total.toLocaleString('ru-RU')} ta`;
      clear(tabBox).appendChild(tabs([{ key: 'active', label: 'Faol', count: r.counts.active }, { key: 'deactivated', label: 'Deaktivatsiya qilingan', count: r.counts.deactivated },
        { key: 'no_biometric', label: 'Biometrikasiz', count: r.counts.no_biometric }, { key: 'all', label: 'Hammasi', count: r.counts.all }], st.tab, (k) => { st.tab = k; st.offset = 0; selected.clear(); refresh(); }));
      if (!r.counts.all) return emptyState({ icon: '👥', title: "Hali xodim yo'q", text: 'Birinchi xodimni qo\'shing yoki Excel fayldan import qiling',
        action: h('div', { class: 'row' }, app.can('employee.write') ? btn("Xodim qo'shish", { onClick: () => app.go('/employees/new') }) : null, app.can('employee.import') ? btn('Import', { variant: 'secondary', onClick: () => app.go('/employees/import') }) : null) });
      const cols = [
        { key: 'personnel_no', label: 'Tabel №', sort: true }, { key: 'name', label: 'F.I.Sh.', sort: true, render: (e) => `${e.last_name} ${e.first_name}${e.middle_name ? ` ${e.middle_name}` : ''}` },
        { key: 'department', label: "Bo'lim", sort: true, render: (e) => e.department_name }, { key: 'position_name', label: 'Lavozim' }, { key: 'team', label: 'Brigada' },
        { key: 'biometric_status', label: 'Biometrika', render: (e) => bioBadge(e.biometric_status) },
        r.sensitive ? { key: 'alt', label: 'Muqobil usul', render: (e) => [e.card_no ? 'karta' : null, e.has_pin ? 'PIN' : null].filter(Boolean).join(' + ') || '—' } : null,
        { key: 'status', label: 'Holat', render: (e) => statusBadge(e.status) }, { key: 'last_event_at', label: 'Oxirgi kirish', render: (e) => (e.last_event_at ? relTime(e.last_event_at) : '—') },
      ].filter(Boolean);
      return [table({ rows: r.items, columns: cols, onRow: (e) => app.go(`/employees/${e.id}`), selectable: app.can('employee.write'), selected, onSelect: bulkBar,
        sort: { key: st.sort, dir: 'asc' }, onSort: (s) => { st.sort = s.key === 'name' ? 'name' : s.key === 'department' ? 'department' : 'personnel_no'; refresh(); },
        empty: emptyState({ title: 'Mos xodim topilmadi', action: btn('Filtrlarni tozalash', { variant: 'secondary', onClick: () => { Object.assign(st, { q: '', department_id: '', position_id: '', team: '', biometric_status: '' }); Object.values(f).forEach((x) => { x.value = ''; }); refresh(); } }) }) }),
      pagination({ total: r.total, limit: st.limit, offset: st.offset, onChange: (p) => { Object.assign(st, p); refresh(); } })];
    });
    bulkBar();
  }
  await refresh();
}

function exportModal(app) {
  const fmt = select([['xlsx', 'Excel (XLSX)'], ['csv', 'CSV']]);
  const sens = checkbox("Shaxsiy maydonlarni qo'shish (telefon, tug'ilgan sana, PINFL oxirgi 4 raqam)");
  const reason = textarea({ rows: 2, placeholder: 'Shaxsiy maydonlar uchun sabab (kamida 10 belgi)' });
  const rf = field({ label: 'Sabab', input: reason });
  rf.hidden = true;
  sens.input.addEventListener('change', () => { rf.hidden = !sens.input.checked; });
  if (!app.can('employee.read_sensitive')) sens.hidden = true;
  const m = modal({ title: 'Xodimlarni eksport qilish', body: [field({ label: 'Format', input: fmt }), sens, rf, h('div', { class: 'caption' }, 'Fayl 24 soat saqlanadi. Eksport auditga yoziladi.')],
    footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn('Eksport', { onClick: async () => {
      if (sens.input.checked && reason.value.trim().length < 10) { rf.setError('Kamida 10 belgi'); return; }
      try { const r = await app.api.post('/api/v1/employees/export', { format: fmt.value, include_sensitive: sens.input.checked, reason: reason.value.trim() || null });
        await app.api.download(`/api/v1/exports/${r.export_id}/download`); m.close(); toast(`${r.rows} ta xodim eksport qilindi`, 'success'); }
      catch (e) { showError(e); }
    } })] });
}

// ---------------------------------------------------------------- SCR-11 form
export async function renderForm(main, params, app) {
  const editing = !!params.id;
  const tree = await orgTree(app, true);
  let emp = null;
  if (editing) { try { emp = await app.api.get(`/api/v1/employees/${params.id}`); } catch (e) { main.appendChild(errorState(e)); return; } }
  const sites = tree.sites;
  const siteOpts = sites.map((s) => [s.id, s.name]);
  const deptFor = (siteId) => (sites.find((s) => s.id === siteId)?.departments || []).filter((d) => d.status === 'active').map((d) => [d.id, d.name]);
  const firstSite = emp?.site_id || sites[0]?.id;
  const f = form([
    { name: 'personnel_no', label: 'Tabel raqami', required: true, maxlength: 20, regex: '^[A-Za-z0-9-]+$', regexMessage: 'Faqat harf, raqam va "-"', readonly: editing, help: editing ? "Tabel raqami o'zgartirilmaydi" : 'Zavod ichida yagona' },
    { name: 'last_name', label: 'Familiya', required: true, maxlength: 60 }, { name: 'first_name', label: 'Ism', required: true, maxlength: 60 },
    { name: 'middle_name', label: 'Otasining ismi', maxlength: 60 },
    app.can('employee.read_sensitive') ? { name: 'pinfl', label: 'PINFL (JSHSHIR)', maxlength: 14, regex: '^\\d{14}$', regexMessage: '14 ta raqam', inputmode: 'numeric', help: editing && emp?.pinfl_masked ? `Joriy: ${emp.pinfl_masked} (o'zgartirish uchun yangisini kiriting)` : 'Shifrlangan saqlanadi' } : null,
    app.can('employee.read_sensitive') ? { name: 'birth_date', label: "Tug'ilgan sana", type: 'date' } : null,
    app.can('employee.read_sensitive') ? { name: 'phone', label: 'Telefon', placeholder: '+998901234567', regex: '^\\+\\d{9,15}$', regexMessage: '+998XXXXXXXXX formatida' } : null,
    { name: 'site_id', label: 'Zavod', type: 'select', options: siteOpts, required: true, readonly: editing },
    { name: 'department_id', label: "Bo'lim", type: 'select', options: deptFor(firstSite), required: true },
    { name: 'position_id', label: 'Lavozim', type: 'select', options: [['', '—'], ...tree.positions.map((p) => [p.id, p.name])] },
    { name: 'team', label: 'Smena brigadasi', type: 'select', options: [['', '—'], ['A', 'A'], ['B', 'B'], ['C', 'C'], ['D', 'D']] },
    { name: 'hire_date', label: 'Ishga kirgan sana', type: 'date', required: true, readonly: editing, value: todayISO(app.tz) },
    { name: 'card_no', label: 'RFID karta №', maxlength: 32, help: 'Muqobil identifikatsiya (rozilik bermaganlar uchun majburiy)' },
    { name: 'pin', label: editing && emp?.has_pin ? 'Yangi PIN (ixtiyoriy)' : 'PIN-kod', type: 'password', regex: '^\\d{4,6}$', regexMessage: '4–6 raqam', inputmode: 'numeric', validate: (v) => (v && ['0000', '1111', '1234', '12345', '123456'].includes(v) ? 'PIN juda oddiy' : '') },
    { name: 'language', label: 'Bildirishnoma tili', type: 'select', options: [['uz', "O'zbek"], ['ru', 'Русский'], ['en', 'English']] },
  ].filter(Boolean), emp ? { ...emp, pinfl: '', phone: emp.phone, birth_date: emp.birth_date } : { site_id: firstSite });
  const siteSel = f.fields.site_id.ctl, deptSel = f.fields.department_id.ctl;
  siteSel.addEventListener('change', () => { clear(deptSel); deptFor(siteSel.value).forEach(([v, l]) => deptSel.appendChild(h('option', { value: v }, l))); });
  if (emp) deptSel.value = emp.department_id;
  const initial = JSON.stringify(f.values());
  const dirty = () => JSON.stringify(f.values()) !== initial;
  window.onbeforeunload = () => (dirty() ? true : undefined);
  const save = btn('Saqlash', { onClick: async () => {
    if (!f.validate()) return;
    const v = f.values();
    for (const k of Object.keys(v)) if (v[k] === null) delete v[k];
    try {
      let saved;
      if (editing) {
        const patch = { version: emp.version };
        for (const k of ['last_name', 'first_name', 'middle_name', 'pinfl', 'birth_date', 'phone', 'department_id', 'position_id', 'team', 'card_no', 'pin', 'language']) if (k in v) patch[k] = v[k];
        saved = await app.api.patch(`/api/v1/employees/${emp.id}`, patch);
      } else {
        saved = await app.api.post('/api/v1/employees', v);
        if (saved.duplicate_warnings?.length) toast(`Diqqat: ${saved.duplicate_warnings.length} ta mumkin bo'lgan takroriy xodim topildi`, 'warning');
      }
      window.onbeforeunload = null;
      toast('Xodim saqlandi', 'success');
      app.go(`/employees/${saved.id}${editing ? '' : '?new=1'}`);
    } catch (e) {
      if (e.code === 'VERSION_CONFLICT') toast("Ma'lumot boshqa foydalanuvchi tomonidan o'zgartirildi. Sahifani yangilang.", 'error');
      else if (e.code === 'PERSONNEL_NO_TAKEN') { f.fields.personnel_no.wrap.setError(e.message); }
      else if (e.code === 'CARD_TAKEN') { f.fields.card_no.wrap.setError(e.message); }
      else showError(e, f);
    }
  } });
  main.append(pageHead(editing ? `Tahrirlash: ${emp.last_name} ${emp.first_name}` : "Yangi xodim", null, [], [['Xodimlar', '/employees'], [editing ? emp.personnel_no : 'Yangi']]),
    h('div', { class: 'card pad-lg' }, f.el),
    h('div', { class: 'sticky-bar' }, btn('Bekor qilish', { variant: 'tertiary', onClick: () => { if (!dirty() || window.confirm("Saqlanmagan o'zgarishlar bor. Chiqasizmi?")) { window.onbeforeunload = null; history.back(); } } }), save));
}

// ---------------------------------------------------------------- SCR-12 profile
export async function renderProfile(main, params, app) {
  let emp;
  try { emp = await app.api.get(`/api/v1/employees/${params.id}`); } catch (e) { main.appendChild(errorState(e)); return; }
  const isNew = app.query().new === '1';
  const tabBox = h('div'), body = h('div');
  const actions = [];
  if (app.can('biometric.enroll') && emp.status === 'active') actions.push(btn(emp.biometric_status === 'active' ? "Qayta ro'yxatdan o'tkazish" : "Yuzni ro'yxatdan o'tkazish", { variant: emp.biometric_status === 'active' ? 'secondary' : 'primary', onClick: () => app.go(`/employees/${emp.id}/enroll`) }));
  if (app.can('employee.write')) actions.push(btn('Tahrirlash', { variant: 'secondary', onClick: () => app.go(`/employees/${emp.id}/edit`) }));
  const more = btn('', { variant: 'icon', icon: '⋯', title: 'Amallar', onClick: () => menu(more, [
    app.can('employee.write') ? { label: 'Portal kirishini berish', onClick: () => grantPortal() } : null,
    app.can('correction.request') ? { label: 'Davomat jurnali', onClick: () => app.go(`/attendance/events?employee_id=${emp.id}`) } : null,
    app.can('employee.deactivate') && emp.status === 'active' ? { label: 'Deaktivatsiya', danger: true, onClick: () => deactivate() } : null,
    app.can('employee.deactivate') && emp.status !== 'active' ? { label: 'Qayta faollashtirish', onClick: async () => { const r = await act(() => app.api.post(`/api/v1/employees/${emp.id}/reactivate`), 'Faollashtirildi'); if (r) { if (r.needs_enrollment) toast("Biometrika qayta ro'yxatdan o'tkazilishi kerak", 'warning'); app.go(`/employees/${emp.id}`); } } } : null]) });
  actions.push(more);
  main.append(pageHead(`${emp.last_name} ${emp.first_name}`, null, actions, [['Xodimlar', '/employees'], [emp.personnel_no]]));
  if (isNew && emp.biometric_status === 'none' && app.can('biometric.enroll')) main.appendChild(h('div', { class: 'note', style: { marginBottom: '12px' } }, 'Xodim saqlandi. ', h('a', { href: `/app/employees/${emp.id}/enroll`, 'data-link': '' }, "Yuzni ro'yxatdan o'tkazish"), ' yoki karta/PIN berish mumkin.'));
  const side = h('div', { class: 'card stack', style: { alignItems: 'center', textAlign: 'center' } }, h('div', { class: 'avatar lg' }, initials(`${emp.last_name} ${emp.first_name}`)),
    h('strong', {}, `${emp.last_name} ${emp.first_name} ${emp.middle_name || ''}`), h('div', { class: 'caption' }, `${emp.personnel_no} · ${emp.department_name}`),
    h('div', { class: 'row', style: { justifyContent: 'center' } }, statusBadge(emp.status), bioBadge(emp.biometric_status)));
  main.appendChild(h('div', { style: { display: 'grid', gridTemplateColumns: 'minmax(220px, 280px) 1fr', gap: '16px' }, class: 'profile-grid' }, side, h('div', {}, tabBox, body)));
  const TABS = [['general', 'Umumiy'], ['assignments', 'Tayinlovlar'], ['biometric', 'Biometrika'], ['attendance', 'Davomat'], ['leaves', "Ta'til"], ['history', 'Tarix']];
  let tab = app.query().tab || 'general';
  const show = async (k) => {
    tab = k; app.setQuery({ tab: k });
    clear(tabBox).appendChild(tabs(TABS.map(([key, label]) => ({ key, label })), tab, show));
    clear(body);
    if (k === 'general') body.appendChild(h('div', { class: 'card' }, kv([
      ['Tabel №', emp.personnel_no], ['Zavod', emp.site_name], ["Bo'lim", emp.department_name], ['Lavozim', emp.position_name], ['Brigada', emp.team],
      ['Ishga kirgan', fmtDate(emp.hire_date)], emp.pinfl_masked !== undefined ? ['PINFL', emp.pinfl_masked || '—'] : null,
      emp.phone !== undefined ? ['Telefon', emp.phone] : null, emp.birth_date !== undefined ? ["Tug'ilgan sana", fmtDate(emp.birth_date)] : null,
      ['Muqobil usul', [emp.card_no ? `karta ${emp.card_no}` : null, emp.has_pin ? 'PIN' : null].filter(Boolean).join(', ') || '—'],
      ['Kirish nuqtalari', emp.access_points.map((a) => a.name).join(', ')], ['Til', emp.language],
      emp.status !== 'active' ? ['Deaktivatsiya', `${fmtDate(emp.deactivated_at)} · ${emp.deactivation_reason || ''}`] : null])));
    if (k === 'assignments') body.appendChild(table({ rows: emp.assignments, columns: [
      { key: 'valid_from', label: 'Dan', render: (a) => fmtDate(a.valid_from) }, { key: 'valid_to', label: 'Gacha', render: (a) => (a.valid_to ? fmtDate(a.valid_to) : 'hozirgacha') },
      { key: 'department_name', label: "Bo'lim" }, { key: 'position_name', label: 'Lavozim' }, { key: 'team', label: 'Brigada' }] }));
    if (k === 'biometric') {
      const b = emp.biometric;
      body.appendChild(h('div', { class: 'card stack' }, kv([
        ['Holat', bioBadge(emp.biometric_status)], ['Rozilik', b.consent ? `${b.consent.decision} · ${fmtDate(b.consent.created_at, app.tz)} · v${b.consent.policy_version}` : 'qayd etilmagan'],
        b.profile ? ["Ro'yxatdan o'tgan", fmtDateTime(b.profile.created_at, app.tz)] : null, b.profile ? ['Model', h('span', { class: 'mono' }, b.profile.model_version)] : null,
        b.profile ? ['Sifat / liveness', `${(b.profile.quality_score * 100).toFixed(0)}% / ${b.profile.liveness_score ?? '—'}`] : null,
        b.profile ? ['Kadrlar soni', b.profile.frames] : null, ['Oxirgi yuz bo\'yicha tanish', b.last_face_match_at ? fmtDateTime(b.last_face_match_at, app.tz) : '—']]),
      h('div', { class: 'caption' }, 'Enrollment suratlari saqlanmaydi. Shablon shifrlangan, eksport qilinmaydi.'),
      h('div', { class: 'row' }, app.can('biometric.enroll') && emp.status === 'active' ? btn(b.profile ? "Qayta ro'yxatdan o'tkazish" : "Yuzni ro'yxatdan o'tkazish", { onClick: () => app.go(`/employees/${emp.id}/enroll`) }) : null,
        app.can('biometric.revoke') && b.profile ? btn('Biometrik profilni bekor qilish', { variant: 'danger-outline', onClick: () => revoke() }) : null)));
    }
    if (k === 'attendance') {
      const box = h('div'); body.appendChild(box);
      const to = todayISO(app.tz), from = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
      await load(box, () => app.api.get('/api/v1/attendance/daily-summaries', { query: { from, to, employee_id: emp.id } }), (r) => {
        const days = Object.values(r.days[emp.id] || {}).sort((a, b) => (a.work_date < b.work_date ? 1 : -1));
        return table({ rows: days, dense: true, columns: [{ key: 'work_date', label: 'Sana', render: (s) => fmtDate(s.work_date) }, { key: 'shift_code', label: 'Smena' },
          { key: 'status', label: 'Holat', render: (s) => statusBadge(s.status) }, { key: 'worked_min', label: 'Ishlangan', render: (s) => fmtDuration(s.worked_min) },
          { key: 'late_min', label: 'Kechikish', num: true }, { key: 'explanation', label: 'Izoh', wrap: true }], empty: emptyState({ title: "Oxirgi 30 kunda ma'lumot yo'q" }) });
      });
    }
    if (k === 'leaves') { const box = h('div'); body.appendChild(box); await load(box, () => app.api.get('/api/v1/leaves', { query: { employee_id: emp.id } }), (r) => table({ rows: r.items, columns: [
      { key: 'type', label: 'Turi' }, { key: 'range', label: 'Davr', render: (l) => `${fmtDate(l.start_date)} – ${fmtDate(l.end_date)}` }, { key: 'status', label: 'Holat', render: (l) => statusBadge(l.status) }, { key: 'reason', label: 'Sabab', wrap: true }] })); }
    if (k === 'history') { const box = h('div'); body.appendChild(box); await load(box, () => app.api.get(`/api/v1/employees/${emp.id}/history`), (r) => table({ rows: r.items, columns: [
      { key: 'created_at', label: 'Vaqt', render: (a) => fmtDateTime(a.created_at, app.tz) }, { key: 'action', label: 'Amal' }, { key: 'actor_name', label: 'Kim' },
      { key: 'after_json', label: "O'zgarish", wrap: true, render: (a) => h('span', { class: 'mono' }, (a.after_json || '').slice(0, 160)) }], empty: emptyState({ title: 'Tarix bo\'sh yoki ruxsat yo\'q' }) })); }
  };
  await show(tab);

  function revoke() {
    confirmDanger({ title: 'Biometrik profilni bekor qilish', consequences: ['Shablon kriptografik o\'chiriladi (tiklab bo\'lmaydi)', 'Terminallar galereyasidan olib tashlanadi', 'Xodim karta/PIN orqali o\'tadi'],
      extra: (() => { const s = select([['wrong_profile', "Xato profil"], ['consent_withdrawn', 'Rozilik qaytarildi'], ['security', 'Xavfsizlik'], ['other', 'Boshqa']]); revoke.sel = s; return field({ label: 'Sabab', input: s }); })(),
      confirmWord: "O'CHIRISH", okLabel: 'Bekor qilish', onConfirm: async ({ word }) => {
        const r = await app.api.post(`/api/v1/biometrics/profiles/${emp.id}/revoke`, { reason: revoke.sel.value, confirm: word });
        toast('Biometrik profil bekor qilindi', 'success');
        if (r.needs_alternative_method) toast('Xodimga karta yoki PIN bering', 'warning');
        app.go(`/employees/${emp.id}?tab=biometric`);
      } });
  }
  function deactivate() {
    const dateIn = input({ type: 'date', value: todayISO(app.tz) });
    const reason = select([['dismissed', "Ishdan bo'shatildi"], ['transferred', "O'tkazildi"], ['other', 'Boshqa']]);
    const comment = textarea({ rows: 2 });
    confirmDanger({ title: `Deaktivatsiya: ${emp.last_name} ${emp.first_name}`,
      consequences: ['Terminallar galereyasidan 5 daqiqa ichida olib tashlanadi', 'Portal hisobi bloklanadi', 'Biometrik profil siyosatga ko\'ra N kundan so\'ng o\'chiriladi'],
      extra: h('div', { class: 'form-grid' }, field({ label: 'Sana', input: dateIn }), field({ label: 'Sabab', input: reason }), h('div', { class: 'full' }, field({ label: 'Izoh', input: comment }))),
      okLabel: 'Deaktivatsiya', onConfirm: async () => {
        try { await app.api.post(`/api/v1/employees/${emp.id}/deactivate`, { effective_date: dateIn.value, reason: reason.value, comment: comment.value || null }); toast('Xodim deaktivatsiya qilindi', 'success'); app.go(`/employees/${emp.id}`); }
        catch (e) { if (e.code === 'PENDING_CORRECTIONS') throw new Error(`Ochiq tuzatishlar bor (${e.details.corrections.length}). Avval ularni hal qiling.`); throw e; }
      } });
  }
  async function grantPortal() {
    const r = await act(() => app.api.post(`/api/v1/employees/${emp.id}/portal-access`));
    if (!r) return;
    const m = modal({ title: 'Portal kirishi', body: [kv([['Tashkilot', r.org], ['Login', r.login], ['Amal qiladi', `${r.expires_in_days} kun`]]),
      h('div', { class: 'note' }, 'Faollashtirish havolasini xodimga bering (bir martalik):'), h('input', { class: 'input mono', readonly: true, value: r.activation_link, onclick: (e) => e.target.select() })],
      footer: [btn('Nusxalash', { variant: 'secondary', onClick: () => navigator.clipboard?.writeText(r.activation_link).then(() => toast('Nusxalandi', 'success')) }), btn('Yopish', { onClick: () => m.close() })] });
  }
}

// ---------------------------------------------------------------- SCR-13 import
export async function renderImport(main, params, app) {
  let step = 1, batch = null;
  const stepper = h('div', { class: 'stepper' }), box = h('div', { class: 'card pad-lg stack' });
  main.append(pageHead('Xodimlarni import qilish', 'CSV yoki XLSX, 10 000 qatorgacha', [], [['Xodimlar', '/employees'], ['Import']]), stepper, box);
  const draw = () => { clear(stepper); ['Fayl', 'Tekshiruv', 'Natija'].forEach((s, i) => stepper.appendChild(h('span', { class: `step ${i + 1 === step ? 'active' : i + 1 < step ? 'done' : ''}` }, `${i + 1}. ${s}`))); };
  function step1() {
    step = 1; draw(); clear(box);
    const file = h('input', { type: 'file', accept: '.csv,.xlsx', class: 'input', style: { paddingTop: '8px' } });
    const err = h('div', { class: 'note danger', hidden: true });
    box.append(h('p', {}, "1) Shablonni yuklab oling va to'ldiring. 2) Faylni tanlang. Ustunlar: ", h('span', { class: 'mono' }, 'personnel_no, last_name, first_name, site_code, department_code, hire_date …')),
      btn('Shablonni yuklab olish', { variant: 'secondary', onClick: () => app.api.download('/api/v1/employees/import-template', 'fras-xodimlar-shablon.xlsx') }),
      field({ label: 'Fayl', input: file, help: 'Maksimal 10 MB' }), err,
      h('div', { class: 'btn-bar' }, btn('Davom etish', { onClick: async () => {
        const fl = file.files[0];
        if (!fl) { err.hidden = false; err.textContent = 'Faylni tanlang'; return; }
        if (fl.size > 10 * 1024 * 1024) { err.hidden = false; err.textContent = 'Fayl 10 MB dan katta'; return; }
        const fd = new FormData(); fd.append('file', fl);
        try { batch = await app.api.request('POST', '/api/v1/employees/imports', { form: fd }); step2(); }
        catch (e) { err.hidden = false; err.textContent = e.message; }
      } })));
  }
  function step2() {
    step = 2; draw(); clear(box);
    const s = batch.summary;
    box.append(h('div', { class: 'grid cols-3' }, h('div', { class: 'kpi' }, h('div', { class: 'label' }, 'Yangi'), h('div', { class: 'value' }, s.new)),
      h('div', { class: 'kpi' }, h('div', { class: 'label' }, 'Yangilanadi'), h('div', { class: 'value' }, s.update)), h('div', { class: `kpi ${s.error ? 'danger' : ''}` }, h('div', { class: 'label' }, "Xato (o'tkazib yuboriladi)"), h('div', { class: 'value' }, s.error))),
      table({ dense: true, rows: batch.rows, columns: [{ key: 'row', label: 'Qator', num: true }, { key: 'status', label: 'Holat', render: (r) => badge({ new: 'Yangi', update: 'Yangilanadi', error: 'Xato' }[r.status], r.status === 'error' ? 'danger' : r.status === 'new' ? 'success' : 'info') },
        { key: 'no', label: 'Tabel №', render: (r) => r.data.personnel_no }, { key: 'name', label: 'F.I.Sh.', render: (r) => `${r.data.last_name || ''} ${r.data.first_name || ''}` },
        { key: 'errors', label: 'Xatolar', wrap: true, render: (r) => r.errors.join('; ') }] }),
      batch.total_rows > batch.rows.length ? h('div', { class: 'caption' }, `Birinchi ${batch.rows.length} qator ko'rsatildi (jami ${batch.total_rows})`) : null,
      h('div', { class: 'btn-bar' }, btn('Orqaga', { variant: 'tertiary', onClick: step1 }), btn(`${s.new} yangi, ${s.update} yangilanadi — tasdiqlash`, { disabled: !(s.new + s.update), onClick: async () => {
        try { const r = await app.api.post(`/api/v1/employees/imports/${batch.id}/apply`); step3(r); } catch (e) { showError(e); }
      } })));
  }
  function step3(r) {
    step = 3; draw(); clear(box);
    box.append(h('div', { class: 'note success' }, `${r.created} ta yangi xodim yaratildi, ${r.updated} ta yangilandi.`),
      r.errors.length ? table({ dense: true, rows: r.errors, columns: [{ key: 'row', label: 'Qator' }, { key: 'error', label: 'Xato', wrap: true }] }) : null,
      h('div', { class: 'btn-bar' }, btn('Yana import', { variant: 'secondary', onClick: step1 }), btn("Xodimlar ro'yxati", { onClick: () => app.go('/employees') })));
  }
  step1();
}

// ---------------------------------------------------------------- SCR-14 duplicates
export async function renderDuplicates(main, params, app) {
  const box = h('div');
  main.append(pageHead('Takroriy xodimlar', 'PINFL, F.I.Sh.+tug\'ilgan sana yoki yuz o\'xshashligi bo\'yicha topilgan juftliklar', [], [['Xodimlar', '/employees'], ['Takroriylar']]), box);
  const REASON = { pinfl: 'PINFL bir xil', name_birth: "F.I.Sh. + tug'ilgan sana", face: "Yuz o'xshashligi" };
  async function refresh() {
    await load(box, () => app.api.get('/api/v1/employees/duplicates'), (r) => (r.items.length ? h('div', { class: 'grid cols-2' }, r.items.map((d) => h('div', { class: 'card stack' },
      h('div', { class: 'row' }, badge(REASON[d.reason] || d.reason, d.reason === 'face' ? 'danger' : 'warning')),
      h('div', { class: 'grid cols-2' }, ...[['a', d.employee_a], ['b', d.employee_b]].map(([k, id]) => h('div', { class: 'card' }, h('strong', {}, `${d[`${k}_last`]} ${d[`${k}_first`]}`), h('div', { class: 'caption' }, `${d[`${k}_no`]} · ${d[`${k}_status`]}`),
        h('a', { href: `/app/employees/${id}`, 'data-link': '' }, 'Profil')))),
      h('div', { class: 'btn-bar' }, btn('Turli odamlar', { variant: 'secondary', onClick: async () => { if (await act(() => app.api.post(`/api/v1/employees/duplicates/${d.id}/distinct`), 'Belgilandi')) refresh(); } }),
        btn('Birlashtirish', { onClick: () => merge(d) }))))) : emptyState({ icon: '✓', title: "Takroriy juftliklar yo'q" })));
  }
  function merge(d) {
    const primary = select([[d.employee_a, `${d.a_last} ${d.a_first} (${d.a_no})`], [d.employee_b, `${d.b_last} ${d.b_first} (${d.b_no})`]]);
    confirmDanger({ title: 'Xodimlarni birlashtirish', consequences: ['Ikkinchi yozuv deaktivatsiya qilinadi', "Bo'sh maydonlar asosiy yozuvga ko'chiriladi", 'Asl davomat hodisalari o\'z yozuvida qoladi'],
      extra: field({ label: 'Asosiy yozuv', input: primary }), reasonMin: 10, reasonLabel: 'Izoh', okLabel: 'Birlashtirish',
      onConfirm: async ({ reason }) => { await app.api.post(`/api/v1/employees/duplicates/${d.id}/merge`, { primary_id: primary.value, comment: reason }); toast('Birlashtirildi', 'success'); refresh(); } });
  }
  await refresh();
}

export { bioBadge };
