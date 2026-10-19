// SCR-40 … SCR-46: shift templates, rotations, schedule grid, calendar, leaves, history.
import { h, clear, btn, select, input, field, form, table, drawer, modal, toast, statusBadge, badge, emptyState, load, popover, confirmDanger, checkbox, showError, textarea, pagination, tabs } from '/assets/core/ui.js';
import { fmtDate, fmtDateTime, todayISO, addDays, daysBetween, weekday, WEEKDAYS } from '/assets/core/format.js';
import { pageHead, departments, orgTree, employeePicker, act, LEAVE_TYPES } from './common.js';

const COLORS = ['blue', 'green', 'amber', 'purple', 'teal', 'rose', 'slate', 'indigo'];
const chip = (code, color) => h('span', { class: `shift-chip sc-${color || 'slate'}` }, code);

// ---------------------------------------------------------------- templates
export async function renderTemplates(main, params, app) {
  const box = h('div'), rotBox = h('div');
  main.append(pageHead('Smena shablonlari', "Tungi smena avtomatik aniqlanadi; o'zgarish yangi versiya sifatida kelajakdan kuchga kiradi", [
    app.can('shift.manage') ? btn('Shablon yaratish', { icon: '+', onClick: () => editTemplate(null) }) : null,
    app.can('shift.manage') ? btn('Rotatsiya yaratish', { variant: 'secondary', onClick: () => newRotation() }) : null]), box, h('h2', { style: { marginTop: '24px' } }, 'Rotatsiyalar'), rotBox);
  async function refresh() {
    await load(box, () => app.api.get('/api/v1/shifts/templates'), (r) => table({ rows: r.items, onRow: app.can('shift.manage') ? (t) => editTemplate(t) : null,
      empty: emptyState({ icon: '◷', title: "Smena shablonlari yo'q", text: 'Kunduzgi (08:00–17:00) va tungi (22:00–06:00) smenalardan boshlang' }), columns: [
        { key: 'code', label: 'Kod', render: (t) => chip(t.code, t.color) }, { key: 'name', label: 'Nomi' }, { key: 'time', label: 'Vaqt', render: (t) => `${t.start_time}–${t.end_time}${t.crosses_midnight ? ' (+1)' : ''}` },
        { key: 'breaks', label: 'Tanaffuslar', render: (t) => t.breaks.map((b) => (b.floating_min ? `${b.floating_min} daq` : `${b.start}–${b.end}`) + (b.paid ? ' (to\'langan)' : '')).join(', ') || '—' },
        { key: 'grace_min', label: 'Grace', render: (t) => `${t.grace_min} daq` }, { key: 'overtime', label: "Qo'shimcha", render: (t) => `≥${t.overtime_min} daq, ${t.overtime_round_min} daq qadam` },
        { key: 'version', label: 'Versiya', render: (t) => `v${t.version} · ${t.valid_from > '2001' ? fmtDate(t.valid_from) : 'boshidan'}` }, { key: 'assigned_days', label: 'Kelgusi tayinlovlar', num: true }] }));
    await load(rotBox, () => app.api.get('/api/v1/shifts/rotations'), (r) => table({ rows: r.items, empty: emptyState({ title: "Rotatsiya yo'q", text: 'Masalan 2/2: D1 D1 N1 N1 OFF OFF' }), columns: [
      { key: 'name', label: 'Nomi' }, { key: 'pattern', label: 'Naqsh', render: (x) => h('span', { class: 'row' }, x.pattern.map((p) => (p === 'OFF' ? badge('dam') : h('span', { class: 'shift-chip sc-slate' }, p)))) },
      { key: 'len', label: 'Tsikl', render: (x) => `${x.pattern.length} kun` },
      { key: 'act', label: '', render: (x) => (app.can('shift.assign') ? btn('Qo\'llash', { variant: 'secondary', size: 's', onClick: () => applyRotation(x) }) : '') }] }));
  }
  function editTemplate(t) {
    const breaks = (t?.breaks || [{ start: '12:00', end: '13:00', paid: false }]).map((b) => ({ ...b }));
    const f = form([
      { name: 'code', label: 'Kod', required: true, maxlength: 12, regex: '^[A-Za-z0-9-]{2,12}$', regexMessage: '2–12 harf/raqam', readonly: !!t },
      { name: 'name', label: 'Nomi', required: true, maxlength: 80 },
      { name: 'start_time', label: 'Boshlanish', type: 'time', required: true }, { name: 'end_time', label: 'Tugash', type: 'time', required: true,
        help: 'Tugash < boshlanish bo\'lsa — yarim tundan o\'tadi; ish kuni boshlanish sanasiga yoziladi' },
      { name: 'grace_min', label: 'Kechikish grace (daq)', type: 'number', min: 0, max: 60 }, { name: 'early_leave_min', label: 'Erta ketish chegarasi (daq)', type: 'number', min: 0, max: 60 },
      { name: 'overtime_min', label: "Qo'shimcha ish minimal (daq)", type: 'number', min: 0, max: 240 }, { name: 'overtime_round_min', label: 'Yaxlitlash qadami (daq)', type: 'number', min: 1, max: 60 },
      { name: 'window_before_min', label: 'Kirish oynasi oldin (daq)', type: 'number', min: 0, max: 360 }, { name: 'window_after_min', label: 'Chiqish oynasi keyin (daq)', type: 'number', min: 0, max: 600 },
      { name: 'count_early_arrival', label: 'Erta kelishni qo\'shimcha ishga qo\'shish', type: 'checkbox' }, { name: 'color', label: 'Rang', type: 'select', options: COLORS.map((c) => [c, c]) },
      t ? { name: 'valid_from', label: 'Yangi versiya amal qiladi', type: 'date', required: true, value: todayISO(app.tz) } : null,
    ].filter(Boolean), t || { grace_min: 5, early_leave_min: 5, overtime_min: 30, overtime_round_min: 15, window_before_min: 120, window_after_min: 240, color: 'blue' });
    const breakBox = h('div', { class: 'stack' });
    const drawBreaks = () => {
      clear(breakBox);
      breaks.forEach((b, i) => {
        const fixed = !b.floating_min;
        const s = input({ type: 'time', value: b.start || '' }), e = input({ type: 'time', value: b.end || '' }), fl = input({ type: 'number', min: 5, max: 120, value: b.floating_min || 30 });
        const kind = select([['fixed', 'Belgilangan vaqt'], ['floating', 'Suzuvchi (daq)']], { value: fixed ? 'fixed' : 'floating' });
        const paid = checkbox("To'langan", {}); paid.input.checked = !!b.paid;
        const sync = () => { if (kind.value === 'fixed') { b.start = s.value; b.end = e.value; delete b.floating_min; } else { b.floating_min = Number(fl.value); delete b.start; delete b.end; } b.paid = paid.input.checked; };
        [s, e, fl, kind, paid.input].forEach((x) => x.addEventListener('change', () => { sync(); drawBreaks(); }));
        breakBox.appendChild(h('div', { class: 'row' }, kind, kind.value === 'fixed' ? [s, '–', e] : [fl, 'daq'], paid, btn('', { variant: 'icon', icon: '✕', title: "Tanaffusni o'chirish", onClick: () => { breaks.splice(i, 1); drawBreaks(); } })));
      });
      breakBox.appendChild(btn("Tanaffus qo'shish", { variant: 'tertiary', size: 's', onClick: () => { breaks.push({ floating_min: 30, paid: false }); drawBreaks(); } }));
    };
    drawBreaks();
    const d = drawer({ title: t ? `Smena ${t.code}: yangi versiya` : 'Yangi smena shabloni', size: 'w720', body: [f.el, h('fieldset', {}, h('legend', {}, 'Tanaffuslar'), breakBox),
      t ? h('div', { class: 'note' }, "Ishlatilayotgan shablon o'zgarsa, yangi versiya tanlangan sanadan amal qiladi; o'tgan kunlar eski versiya bilan hisoblanadi.") : null],
    footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => d.close() }), btn('Saqlash', { onClick: async () => {
      if (!f.validate()) return;
      const v = f.values();
      const payload = { ...v, breaks: breaks.map((b) => (b.floating_min ? { floating_min: b.floating_min, paid: !!b.paid } : { start: b.start, end: b.end, paid: !!b.paid })) };
      for (const k of ['grace_min', 'early_leave_min', 'overtime_min', 'overtime_round_min', 'window_before_min', 'window_after_min']) if (payload[k] === null) delete payload[k];
      try {
        const r = t ? await app.api.put(`/api/v1/shifts/templates/${t.code}`, { ...payload, code: t.code }) : await app.api.post('/api/v1/shifts/templates', payload);
        toast(r.message || 'Smena saqlandi', 'success'); d.close(); refresh();
      } catch (e) { showError(e, f); }
    } })] });
  }
  async function newRotation() {
    const tpls = (await app.api.get('/api/v1/shifts/templates')).items;
    const name = input({ placeholder: 'Masalan: 2/2 kun-tun' });
    const pattern = input({ placeholder: 'D1 D1 N1 N1 OFF OFF', help: '' });
    const m = modal({ title: 'Yangi rotatsiya', body: [field({ label: 'Nomi', required: true, input: name }),
      field({ label: 'Naqsh (bo\'sh joy bilan)', required: true, input: pattern, help: `Kodlar: ${tpls.map((t) => t.code).join(', ')}, dam olish — OFF` })],
    footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn('Yaratish', { onClick: async () => {
      const p = pattern.value.trim().toUpperCase().split(/\s+/).filter(Boolean);
      if (await act(() => app.api.post('/api/v1/shifts/rotations', { name: name.value, pattern: p }), 'Rotatsiya yaratildi')) { m.close(); refresh(); }
    } })] });
  }
  async function applyRotation(rot) {
    const depts = await departments(app);
    const dept = select(depts.map((d) => [d.id, `${d.name} (${d.site_name})`]));
    const start = input({ type: 'date', value: todayISO(app.tz) }), end = input({ type: 'date', value: addDays(todayISO(app.tz), 27) });
    const offs = { A: input({ type: 'number', value: 0, min: 0 }), B: input({ type: 'number', value: 2, min: 0 }), C: input({ type: 'number', value: 4, min: 0 }), D: input({ type: 'number', value: 6, min: 0 }) };
    const result = h('div');
    const payload = (preview) => ({ department_id: dept.value, start_date: start.value, end_date: end.value, preview, team_offsets: Object.fromEntries(Object.entries(offs).map(([k, v]) => [k, Number(v.value)])) });
    const m = modal({ title: `Rotatsiyani qo'llash: ${rot.name}`, size: 'w640', body: [field({ label: "Bo'lim", input: dept }), h('div', { class: 'form-grid' }, field({ label: 'Dan', input: start }), field({ label: 'Gacha', input: end })),
      h('fieldset', {}, h('legend', {}, 'Brigadalar siljishi (kun)'), h('div', { class: 'row' }, Object.entries(offs).map(([k, v]) => field({ label: `Brigada ${k}`, input: v })))), result],
    footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }),
      btn('Preview', { variant: 'secondary', onClick: async () => { try { const r = await app.api.post(`/api/v1/shifts/rotations/${rot.id}/apply`, payload(true), { idempotent: false });
        clear(result).append(h('div', { class: 'note' }, `${r.employees} xodim, ${r.assignments} tayinlov. Konfliktlar: ${r.conflicts.length}`), r.conflicts.length ? h('div', { class: 'note warning' }, `Dam olish ${'<'} talab: ${r.conflicts.slice(0, 5).map((c) => c.work_date).join(', ')}…`) : null); } catch (e) { showError(e); } } }),
      btn('Qo\'llash', { onClick: async () => { const r = await act(() => app.api.post(`/api/v1/shifts/rotations/${rot.id}/apply`, payload(false))); if (r) { toast(`${r.assignments} tayinlov yaratildi`, 'success'); m.close(); } } })] });
  }
  await refresh();
}

// ---------------------------------------------------------------- schedule grid (SCR-42)
export async function renderSchedule(main, params, app) {
  const q = app.query();
  const monday = (iso) => addDays(iso, -((weekday(iso) + 6) % 7));
  const st = { from: q.from || monday(todayISO(app.tz)), days: Number(q.days || 14), department_id: q.department_id || '', team: q.team || '' };
  const preselected = (q.employees || '').split(',').filter(Boolean);
  const depts = await departments(app).catch(() => []);
  const fromIn = input({ type: 'date', value: st.from });
  const daysSel = select([[7, '1 hafta'], [14, '2 hafta'], [31, '1 oy']], { value: st.days });
  const deptSel = select([['', "Barcha bo'limlar"], ...depts.map((d) => [d.id, d.name])], { value: st.department_id });
  const teamSel = select([['', 'Barcha brigadalar'], ['A', 'A'], ['B', 'B'], ['C', 'C'], ['D', 'D']], { value: st.team });
  [[fromIn, 'from'], [daysSel, 'days'], [deptSel, 'department_id'], [teamSel, 'team']].forEach(([el, k]) => el.addEventListener('change', () => { st[k] = k === 'days' ? Number(el.value) : el.value; refresh(); }));
  const box = h('div');
  main.append(pageHead('Ish jadvali', 'Katakni bosing yoki Enter — smena tanlash. Qizil ramka — dam olish vaqti yetarli emas', [
    app.can('shift.assign') ? btn('Ommaviy biriktirish', { variant: 'secondary', onClick: () => bulkModal() }) : null,
    app.can('shift.assign') ? btn("Haftani nusxalash", { variant: 'secondary', onClick: () => copyWeek() }) : null,
    app.can('audit.read') ? btn('Tarix', { variant: 'tertiary', onClick: () => app.go('/shifts/history') }) : null]),
  h('div', { class: 'filters' }, field({ label: 'Boshlanish', input: fromIn }), field({ label: 'Oraliq', input: daysSel }), field({ label: "Bo'lim", input: deptSel }), field({ label: 'Brigada', input: teamSel }),
    btn('‹', { variant: 'secondary', size: 's', title: 'Oldingi', onClick: () => { st.from = addDays(st.from, -st.days); fromIn.value = st.from; refresh(); } }),
    btn('Bugun', { variant: 'tertiary', size: 's', onClick: () => { st.from = monday(todayISO(app.tz)); fromIn.value = st.from; refresh(); } }),
    btn('›', { variant: 'secondary', size: 's', title: 'Keyingi', onClick: () => { st.from = addDays(st.from, st.days); fromIn.value = st.from; refresh(); } })), box);
  let data = null;
  async function refresh() {
    app.setQuery({ from: st.from, days: st.days, department_id: st.department_id, team: st.team });
    data = await load(box, () => app.api.get('/api/v1/shifts/schedule', { query: { from: st.from, to: addDays(st.from, st.days - 1), department_id: st.department_id || undefined, team: st.team || undefined } }), (r) => {
      const days = daysBetween(r.from, r.to);
      const colors = Object.fromEntries(r.templates.map((t) => [t.code, t.color]));
      const conflict = new Set(r.conflicts.map((c) => `${c.employee_id}|${c.work_date}`));
      const holidays = new Map(r.holidays.map((x) => [x.day, x.name]));
      const locked = (empSite, d) => r.closed_periods.some((p) => p.site_id === empSite && p.start_date <= d && p.end_date >= d);
      if (!r.employees.length) return emptyState({ title: 'Xodimlar topilmadi', text: 'Filtrlarni o\'zgartiring' });
      return h('div', { class: 'table-wrap', style: { maxHeight: 'calc(100vh - 280px)' } }, h('table', { class: 'cal-grid' },
        h('thead', {}, h('tr', {}, h('th', { style: { textAlign: 'left', padding: '0 10px', minWidth: '200px' } }, 'Xodim'),
          days.map((d) => h('th', { class: [0, 6].includes(weekday(d)) || holidays.has(d) ? 'we' : '', title: holidays.get(d) || '' }, h('div', {}, `${d.slice(8)}.${d.slice(5, 7)}`), h('div', { class: 'caption' }, holidays.has(d) ? '★' : WEEKDAYS[weekday(d)]))))),
        h('tbody', {}, r.employees.map((e) => h('tr', {}, h('td', { class: 'name' }, `${e.last_name} ${e.first_name}`, h('span', { class: 'caption' }, ` · ${e.team || '—'}`)),
          days.map((d) => {
            const c = r.cells[e.id]?.[d];
            const isLocked = locked(e.site_id, d);
            const td = h('td', { class: `cell ${conflict.has(`${e.id}|${d}`) ? 'conflict' : ''} ${isLocked ? 'locked' : ''} ${[0, 6].includes(weekday(d)) ? 'we' : ''}`, tabIndex: 0,
              title: isLocked ? 'Davr yopilgan' : conflict.has(`${e.id}|${d}`) ? "Smenalar orasida dam olish yetarli emas" : '' },
            c?.code ? chip(c.code, colors[c.code]) : c ? h('span', { class: 'caption' }, 'dam') : '');
            if (app.can('shift.assign') && !isLocked) {
              const open = () => cellPopover(td, e, d, c?.code, r.templates);
              td.addEventListener('click', open); td.addEventListener('keydown', (ev) => ev.key === 'Enter' && open());
            }
            return td;
          }))))));
    });
  }
  function cellPopover(td, e, d, current, templates) {
    const past = d < todayISO(app.tz);
    const reason = textarea({ rows: 2, placeholder: "O'tgan kun uchun sabab (kamida 10 belgi)" });
    const set = async (code) => {
      if (past && reason.value.trim().length < 10) { toast("O'tgan kunni o'zgartirish uchun sabab kiriting", 'warning'); reason.focus(); return; }
      try { const r = await app.api.put('/api/v1/shifts/schedule/cell', { employee_id: e.id, work_date: d, shift_code: code, reason: reason.value.trim() || null });
        p.close(); if (r.conflicts.length) toast('Diqqat: smenalar orasida dam olish yetarli emas', 'warning'); refresh(); }
      catch (ex) { showError(ex); }
    };
    const p = popover(td, h('div', { class: 'stack small' }, h('strong', {}, `${e.last_name} ${e.first_name} · ${fmtDate(d)}`),
      h('div', { class: 'row' }, templates.map((t) => btn(t.code, { variant: t.code === current ? 'primary' : 'secondary', size: 's', title: `${t.name} ${t.start_time}–${t.end_time}`, onClick: () => set(t.code) })),
        btn('Dam', { variant: current === null ? 'primary' : 'secondary', size: 's', onClick: () => set(null) })),
      past ? h('div', {}, h('div', { class: 'note warning' }, "O'tgan kun: kunlik natija qayta hisoblanadi va auditga yoziladi"), reason) : null));
  }
  async function bulkModal() {
    const tpls = (await app.api.get('/api/v1/shifts/templates')).items;
    const target = select([['dept', "Bo'lim bo'yicha"], ['selected', `Tanlangan xodimlar (${preselected.length})`]], { value: preselected.length ? 'selected' : 'dept' });
    const dept = select(depts.map((d) => [d.id, d.name]), { value: st.department_id || depts[0]?.id });
    const code = select([['', 'Dam olish'], ...tpls.map((t) => [t.code, `${t.code} · ${t.start_time}–${t.end_time}`])]);
    const start = input({ type: 'date', value: st.from }), end = input({ type: 'date', value: addDays(st.from, 13) });
    const wds = [1, 2, 3, 4, 5, 6, 0].map((w) => { const c = checkbox(WEEKDAYS[w]); c.input.checked = w >= 1 && w <= 5; c.w = (w + 6) % 7; return c; });
    const result = h('div');
    const payload = (preview) => ({ ...(target.value === 'dept' ? { department_id: dept.value } : { employee_ids: preselected }), shift_code: code.value || null, start_date: start.value, end_date: end.value, weekdays: wds.filter((c) => c.input.checked).map((c) => c.w), preview });
    const m = modal({ title: 'Ommaviy biriktirish', size: 'w640', body: [field({ label: 'Kimga', input: target }), field({ label: "Bo'lim", input: dept }), field({ label: 'Smena', input: code }),
      h('div', { class: 'form-grid' }, field({ label: 'Dan', input: start }), field({ label: 'Gacha', input: end })), h('div', { class: 'row' }, wds), result],
    footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }),
      btn('Preview', { variant: 'secondary', onClick: async () => { try { const r = await app.api.post('/api/v1/shifts/schedule/bulk', payload(true), { idempotent: false }); clear(result).append(h('div', { class: 'note' }, `${r.employees} xodim, ${r.assignments} kun. Konfliktlar: ${r.conflicts.length}`)); } catch (e) { showError(e); } } }),
      btn("Qo'llash", { onClick: async () => { const r = await act(() => app.api.post('/api/v1/shifts/schedule/bulk', payload(false))); if (r) { toast(`${r.assignments} tayinlov saqlandi`, 'success'); m.close(); refresh(); } } })] });
  }
  function copyWeek() {
    const src = input({ type: 'date', value: monday(st.from) }), dst = input({ type: 'date', value: addDays(monday(st.from), 7) });
    const dept = select(depts.map((d) => [d.id, d.name]), { value: st.department_id || depts[0]?.id });
    const m = modal({ title: 'Haftani nusxalash', body: [field({ label: "Bo'lim", input: dept }), field({ label: 'Manba hafta (dushanba)', input: src }), field({ label: 'Maqsad hafta (dushanba)', input: dst })],
      footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn('Nusxalash', { onClick: async () => { const r = await act(() => app.api.post('/api/v1/shifts/schedule/copy-week', { source_monday: src.value, target_monday: dst.value, department_id: dept.value })); if (r) { toast(`${r.assignments} kun nusxalandi`, 'success'); m.close(); refresh(); } } })] });
  }
  await refresh();
}

// ---------------------------------------------------------------- calendar (SCR-44)
export async function renderCalendar(main, params, app) {
  const tree = await orgTree(app);
  const st = { year: Number(app.query().year || todayISO(app.tz).slice(0, 4)), site_id: app.query().site_id || tree.sites[0]?.id || '' };
  const yearSel = select([st.year - 1, st.year, st.year + 1].map((y) => [y, y]), { value: st.year });
  const siteSel = select(tree.sites.map((s) => [s.id, s.name]), { value: st.site_id });
  [[yearSel, 'year'], [siteSel, 'site_id']].forEach(([el, k]) => el.addEventListener('change', () => { st[k] = k === 'year' ? Number(el.value) : el.value; refresh(); }));
  const box = h('div');
  const KIND = { holiday: ['Bayram', 'danger'], transfer_workday: ["Ko'chirilgan ish kuni", 'info'], exception: ['Istisno', 'warning'] };
  main.append(pageHead('Bayram va istisno kunlari', 'Bayram kunlari jadval va hisob-kitobga ta\'sir qiladi', [app.can('calendar.manage') ? btn("Kun qo'shish", { icon: '+', onClick: () => addDay() }) : null,
    app.can('calendar.manage') ? btn('Import (CSV)', { variant: 'secondary', onClick: () => importDays() }) : null]),
  h('div', { class: 'filters' }, field({ label: 'Yil', input: yearSel }), field({ label: 'Zavod', input: siteSel })), box);
  async function refresh() {
    await load(box, () => app.api.get('/api/v1/calendar', { query: { year: st.year, site_id: st.site_id } }), (r) => table({ rows: r.items, empty: emptyState({ icon: '📅', title: "Bu yil uchun kunlar kiritilmagan" }), columns: [
      { key: 'day', label: 'Sana', render: (d) => `${fmtDate(d.day)} · ${WEEKDAYS[weekday(d.day)]}` }, { key: 'name', label: 'Nomi' }, { key: 'kind', label: 'Turi', render: (d) => badge(...KIND[d.kind]) },
      { key: 'act', label: '', render: (d) => (app.can('calendar.manage') ? btn('', { variant: 'icon', icon: '🗑', title: "O'chirish", onClick: () => confirmDanger({ title: `${d.name} — o'chirish`, consequences: ['Shu kun uchun natijalar qayta hisoblanadi'], okLabel: "O'chirish", onConfirm: async () => { await app.api.del(`/api/v1/calendar/${d.id}`); refresh(); } }) }) : '') }] }));
  }
  function addDay() {
    const f = form([{ name: 'day', label: 'Sana', type: 'date', required: true }, { name: 'name', label: 'Nomi', required: true, minlength: 2 },
      { name: 'kind', label: 'Turi', type: 'select', options: Object.entries(KIND).map(([k, v]) => [k, v[0]]) }]);
    const m = modal({ title: "Kun qo'shish", body: f.el, footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn('Saqlash', { onClick: async () => {
      if (!f.validate()) return;
      try { await app.api.post('/api/v1/calendar', { ...f.values(), site_id: st.site_id }); m.close(); refresh(); toast("Qo'shildi", 'success'); } catch (e) { showError(e, f); }
    } })] });
  }
  function importDays() {
    const ta = textarea({ rows: 8, placeholder: '2026-01-01;Yangi yil\n2026-03-08;Xotin-qizlar kuni\n2026-03-21;Navro\'z' });
    const m = modal({ title: 'Bayramlarni import qilish', body: [h('div', { class: 'caption' }, 'Har qatorda: SANA;NOMI (bayram sifatida qo\'shiladi)'), ta],
      footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn('Import', { onClick: async () => {
        const days = ta.value.split('\n').map((l) => l.split(';')).filter((p) => /^\d{4}-\d{2}-\d{2}$/.test(p[0]?.trim())).map(([d, n]) => ({ site_id: st.site_id, day: d.trim(), name: (n || 'Bayram').trim(), kind: 'holiday' }));
        const r = await act(() => app.api.post('/api/v1/calendar/import', { site_id: st.site_id, days }));
        if (r) { toast(`${r.added} qo'shildi, ${r.skipped} o'tkazib yuborildi`, 'success'); m.close(); refresh(); }
      } })] });
  }
  await refresh();
}

// ---------------------------------------------------------------- leaves (SCR-46)
export async function renderLeaves(main, params, app) {
  const st = { status: app.query().status || '', limit: 50, offset: 0 };
  const tabBox = h('div'), box = h('div');
  main.append(pageHead("Ta'til va yo'qliklar", null, [app.can('leave.request') ? btn("So'rov yaratish", { icon: '+', onClick: () => newLeave() }) : null]), tabBox, box);
  async function refresh() {
    clear(tabBox).appendChild(tabs([['', 'Hammasi'], ['pending', 'Kutilmoqda'], ['approved', 'Tasdiqlangan'], ['rejected', 'Rad etilgan']].map(([key, label]) => ({ key, label })), st.status, (k) => { st.status = k; refresh(); }));
    await load(box, () => app.api.get('/api/v1/leaves', { query: st }), (r) => [table({ rows: r.items, empty: emptyState({ icon: '✈', title: "So'rovlar yo'q" }), columns: [
      { key: 'name', label: 'Xodim', render: (l) => `${l.last_name} ${l.first_name} · ${l.personnel_no}` }, { key: 'department_name', label: "Bo'lim" },
      { key: 'type', label: 'Turi', render: (l) => (LEAVE_TYPES.find((x) => x[0] === l.type) || [0, l.type])[1] },
      { key: 'range', label: 'Davr', render: (l) => `${fmtDate(l.start_date)} – ${fmtDate(l.end_date)}${l.start_time ? ` ${l.start_time}–${l.end_time}` : ''}` },
      { key: 'status', label: 'Holat', render: (l) => statusBadge(l.status) }, { key: 'reason', label: 'Sabab', wrap: true },
      { key: 'act', label: '', render: (l) => (['pending', 'approved'].includes(l.status) && app.can('leave.request') ? btn('Bekor qilish', { variant: 'tertiary', size: 's', onClick: async () => { if (await act(() => app.api.post(`/api/v1/leaves/${l.id}/cancel`), 'Bekor qilindi')) refresh(); } }) : '') }] }),
    pagination({ total: r.total, limit: st.limit, offset: st.offset, onChange: (p) => { Object.assign(st, p); refresh(); } })]);
  }
  function newLeave() {
    const picker = employeePicker(app);
    const f = form([{ name: 'type', label: 'Turi', type: 'select', options: LEAVE_TYPES }, { name: 'start_date', label: 'Dan', type: 'date', required: true, value: todayISO(app.tz) },
      { name: 'end_date', label: 'Gacha', type: 'date', required: true, value: todayISO(app.tz) }, { name: 'start_time', label: 'Soat dan (ruxsat uchun)', type: 'time' },
      { name: 'end_time', label: 'Soat gacha', type: 'time' }, { name: 'reason', label: 'Sabab', type: 'textarea', required: true, full: true, minlength: 3 }]);
    const pf = field({ label: 'Xodim', required: true, input: picker });
    const m = modal({ title: "Ta'til / ruxsat so'rovi", size: 'w640', body: [pf, f.el], footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn('Yuborish', { onClick: async () => {
      if (!picker.value) { pf.setError('Xodimni tanlang'); return; }
      if (!f.validate()) return;
      try { await app.api.post('/api/v1/leaves', { employee_id: picker.value.id, ...f.values() }); toast("So'rov yuborildi", 'success'); m.close(); refresh(); }
      catch (e) { if (e.code === 'LEAVE_BALANCE') toast(`Ta'til qoldig'i yetarli emas: ${e.details.remaining} kun`, 'error'); else if (e.code === 'LEAVE_OVERLAP') toast("Boshqa so'rov bilan kesishadi", 'error'); else showError(e, f); }
    } })] });
  }
  await refresh();
}

export async function renderHistory(main, params, app) {
  const box = h('div');
  main.append(pageHead("Jadval o'zgarishlari tarixi", null, [], [['Jadval', '/shifts/schedule'], ['Tarix']]), box);
  await load(box, () => app.api.get('/api/v1/shifts/history'), (r) => table({ rows: r.items, columns: [
    { key: 'created_at', label: 'Vaqt', render: (a) => fmtDateTime(a.created_at, app.tz) }, { key: 'actor_name', label: 'Kim' }, { key: 'action', label: 'Amal' },
    { key: 'after_json', label: 'Tafsilot', wrap: true, render: (a) => h('span', { class: 'mono' }, (a.after_json || '').slice(0, 200)) }] }));
}
