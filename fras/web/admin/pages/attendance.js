// SCR-30 … SCR-36: journal, event drawer, corrections, timesheet, anomalies, approvals, periods.
import { h, clear, btn, select, input, textarea, field, table, pagination, tabs, drawer, modal, toast, statusBadge, badge, errorState, emptyState, skeletonRows, load, kv, confirmDanger, checkbox, showError, errorText, popover } from '/assets/core/ui.js';
import { fmtDate, fmtTime, fmtDateTime, fmtDuration, todayISO, addDays, daysBetween, weekday, WEEKDAYS, localToUTC } from '/assets/core/format.js';
import { pageHead, departments, employeePicker, act, REASONS } from './common.js';

const RESULT_OPTS = [['', 'Barcha natijalar'], ['accepted', 'Qabul'], ['review', 'Tekshiruvda'], ['unknown', "Noma'lum"], ['pad', 'Soxta tasvir'], ['denied', "Ruxsat yo'q"], ['duplicate', 'Takroriy']];
const METHOD_OPTS = [['', 'Barcha usullar'], ['face', 'Yuz'], ['card_pin', 'Karta/PIN'], ['qr', 'QR'], ['manual', "Qo'lda"], ['guard_override', 'Qo\'riqchi']];

// ---------------------------------------------------------------- SCR-30 journal
export async function renderJournal(main, params, app) {
  const q = app.query();
  const today = todayISO(app.tz);
  const st = { tab: q.tab || 'all', from: q.from || today, to: q.to || q.from || today, q: q.q || '', department_id: q.department_id || '', device_id: q.device_id || '',
    direction: q.direction || '', result: q.result || '', method: q.method || '', employee_id: q.employee_id || '', limit: 50, offset: 0 };
  const depts = await departments(app).catch(() => []);
  let devices = [];
  if (app.can('device.read')) { try { devices = (await app.api.get('/api/v1/devices')).items; } catch { /* ignore */ } }

  const actions = [
    app.can('report.export') ? btn('Eksport', { variant: 'secondary', onClick: () => exportJournal() }) : null,
    app.can('correction.request') ? btn('Tuzatish yaratish', { onClick: () => openCorrectionDrawer(app, {}) }) : null,
  ];
  const tabBox = h('div'), listBox = h('div'), bannerBox = h('div');
  const f = {
    from: input({ type: 'date', value: st.from, max: today }), to: input({ type: 'date', value: st.to, max: today }),
    q: input({ type: 'search', value: st.q, placeholder: 'F.I.Sh. yoki tabel' }),
    department_id: select([['', "Barcha bo'limlar"], ...depts.map((d) => [d.id, d.name])], { value: st.department_id }),
    device_id: select([['', 'Barcha qurilmalar'], ...devices.map((d) => [d.id, d.name])], { value: st.device_id }),
    direction: select([['', "Kirish/chiqish"], ['in', 'Kirish'], ['out', 'Chiqish']], { value: st.direction }),
    result: select(RESULT_OPTS, { value: st.result }), method: select(METHOD_OPTS, { value: st.method }),
  };
  for (const [k, el] of Object.entries(f)) el.addEventListener(k === 'q' ? 'search' : 'change', () => { st[k] = el.value; st.offset = 0; refresh(); });
  f.q.addEventListener('keydown', (e) => { if (e.key === 'Enter') { st.q = f.q.value; st.offset = 0; refresh(); } });
  main.append(pageHead('Davomat jurnali', 'Barcha asl hodisalar — o\'zgartirilmaydi; tuzatishlar alohida qayd etiladi', actions), tabBox,
    h('div', { class: 'filters' }, field({ label: 'Dan', input: f.from }), field({ label: 'Gacha', input: f.to }),
      h('div', { class: 'field grow' }, h('label', {}, 'Qidirish'), f.q), field({ label: "Bo'lim", input: f.department_id }),
      devices.length ? field({ label: 'Qurilma', input: f.device_id }) : null, field({ label: "Yo'nalish", input: f.direction }),
      field({ label: 'Natija', input: f.result }), field({ label: 'Usul', input: f.method }),
      btn('Tozalash', { variant: 'tertiary', size: 's', onClick: () => { Object.assign(st, { from: today, to: today, q: '', department_id: '', device_id: '', direction: '', result: '', method: '', employee_id: '' }); Object.entries(f).forEach(([k, el]) => { el.value = st[k] || ''; }); f.from.value = f.to.value = today; refresh(); } })),
    bannerBox, listBox);

  async function exportJournal() {
    const days = (new Date(st.to) - new Date(st.from)) / 864e5;
    if (days > 93) { toast("Oraliq 93 kundan oshmasin — hisobotlar bo'limidan foydalaning", 'warning'); return; }
    try { await app.api.post('/api/v1/reports/export', { type: 'daily', format: 'csv', params: { date: st.from } }); toast('Eksport tayyorlanmoqda', 'info'); }
    catch (e) { showError(e); }
  }

  async function refresh() {
    app.setQuery({ tab: st.tab, from: st.from, to: st.to, q: st.q, department_id: st.department_id, device_id: st.device_id, direction: st.direction, result: st.result, method: st.method, employee_id: st.employee_id });
    clear(tabBox).appendChild(tabs([{ key: 'all', label: 'Barcha hodisalar' }, { key: 'suspicious', label: 'Shubhali' }, { key: 'duplicate', label: 'Takroriy' }, { key: 'rejected', label: 'Rad etilgan' }, { key: 'late', label: 'Kech kelgan (offline)' }],
      st.tab, (k) => { st.tab = k; st.offset = 0; refresh(); }));
    await load(listBox, () => app.api.get('/api/v1/attendance/events', { query: { ...st, q: st.q || undefined } }), (r) => {
      clear(bannerBox);
      if (r.offline_devices) bannerBox.appendChild(h('div', { class: 'note warning', style: { marginBottom: '8px' } }, `${r.offline_devices} ta qurilma offline — bu oraliq uchun ma'lumot to'liq bo'lmasligi mumkin. `, app.can('device.read') ? h('a', { href: '/app/devices', 'data-link': '' }, 'Qurilmalar') : null));
      return [table({
        rows: r.items, onRow: (e) => openEventDrawer(app, e.id, refresh),
        rowClass: (e) => (['pad', 'unknown', 'denied'].includes(e.result) ? 'flag-danger' : ''),
        empty: emptyState({ icon: '☰', title: 'Tanlangan oraliqda hodisa yo\'q' }),
        columns: [
          { key: 'captured_at', label: 'Vaqt', render: (e) => h('span', { class: 'tabular' }, `${fmtDate(e.captured_at, app.tz)} ${fmtTime(e.captured_at, app.tz, true)}`) },
          { key: 'name', label: 'Xodim', render: (e) => (e.employee_id ? h('span', {}, `${e.last_name} ${e.first_name}`, h('span', { class: 'caption' }, ` · ${e.personnel_no}`)) : h('span', { class: 'muted' }, "Noma'lum shaxs")) },
          { key: 'direction', label: "Yo'n.", render: (e) => (e.direction === 'in' ? '→' : '←') },
          { key: 'access_point_name', label: 'Darvoza' }, { key: 'device_name', label: 'Qurilma' },
          { key: 'method', label: 'Usul', render: (e) => ({ face: 'Yuz', card_pin: 'Karta/PIN', qr: 'QR', manual: "Qo'lda", guard_override: "Qo'riqchi" }[e.method] || e.method) },
          { key: 'result', label: 'Natija', render: (e) => statusBadge(e.result) },
          { key: 'confidence', label: 'Ishonch', render: (e) => (e.confidence ? h('span', { title: e.score !== undefined ? `score ${e.score}` : '' }, { high: 'Yuqori', medium: "O'rta", low: 'Past' }[e.confidence]) : '—') },
          { key: 'review_status', label: 'Tekshiruv', render: (e) => (e.review_status === 'none' ? '—' : statusBadge(e.review_status)) },
          { key: 'flags', label: 'Bayroqlar', render: (e) => h('span', { class: 'row' }, e.late_arrival ? h('span', { title: 'Offline\'dan kech kelgan' }, '⏱') : null, e.clock_suspect ? h('span', { title: 'Soat siljishi' }, '⚠') : null, e.result === 'duplicate' ? h('span', { title: 'Takroriy' }, '↻') : null) },
        ] }), pagination({ total: r.total, limit: st.limit, offset: st.offset, onChange: (p) => { Object.assign(st, p); refresh(); } })];
    });
  }
  await refresh();
}

// ---------------------------------------------------------------- SCR-31 event drawer
export async function openEventDrawer(app, eventId, onChange) {
  const d = drawer({ title: 'Hodisa tafsilotlari', body: skeletonRows(6, 2), size: 'w720' });
  let ev;
  try { ev = await app.api.get(`/api/v1/attendance/events/${eventId}`); } catch (e) { d.setBody(errorState(e)); return; }
  const delay = ev.received_delay_s;
  const captureBox = h('div');
  const body = [
    h('section', {}, h('h3', {}, 'Umumiy'), kv([
      ['Event ID', h('span', { class: 'mono' }, ev.id)], ['Xodim', ev.employee_id ? `${ev.last_name} ${ev.first_name} (${ev.personnel_no})` : "Noma'lum shaxs"],
      ["Yo'nalish", ev.direction === 'in' ? 'Kirish' : 'Chiqish'], ['Qurilma vaqti', fmtDateTime(ev.captured_at, app.tz)],
      ['Server qabul qildi', `${fmtDateTime(ev.received_at, app.tz)}${delay > 120 ? ` (+${Math.round(delay / 60)} daq, offline)` : ''}`],
      ['Darvoza / qurilma', `${ev.access_point_name || '—'} / ${ev.device_name || '—'}`], ['Ish kuni', ev.work_date ? fmtDate(ev.work_date) : '—'],
      ev.clock_suspect ? ['Ogohlantirish', badge('Qurilma soati shubhali', 'warning', '⚠')] : null,
    ])),
    h('section', {}, h('h3', {}, 'Identifikatsiya'), kv([
      ['Usul', ev.method], ['Natija', statusBadge(ev.result)], ['Ishonch', ev.confidence ? { high: 'Yuqori', medium: "O'rta", low: 'Past' }[ev.confidence] : '—'],
      ev.score !== undefined ? ['Score / liveness', `${ev.score ?? '—'} / ${ev.liveness_score ?? '—'}`] : null,
      ev.model_version ? ['Model versiyasi', h('span', { class: 'mono' }, ev.model_version)] : null,
      ['Tekshiruv', ev.review_status === 'none' ? '—' : statusBadge(ev.review_status)],
      ev.review_comment ? ['Izoh', ev.review_comment] : null,
    ])),
    ev.has_capture ? h('section', {}, h('h3', {}, 'Kadr'), h('p', { class: 'caption' }, 'Faqat shubhali hodisalar uchun 30 kun saqlanadi. Har ko\'rish sababi bilan auditga yoziladi.'), captureBox,
      app.can('attendance.capture_view') ? btn("Kadrni ko'rish", { variant: 'secondary', onClick: () => viewCapture() }) : h('div', { class: 'caption' }, "Ko'rish ruxsati yo'q")) : null,
    ev.summary ? h('section', {}, h('h3', {}, 'Ish kuni natijasi'), h('div', { class: 'row' }, statusBadge(ev.summary.status), h('span', {}, ev.summary.explanation))) : null,
    ev.related?.length ? h('section', {}, h('h3', {}, "Shu ish kunining hodisalari"), table({ dense: true, rows: ev.related, columns: [
      { key: 'captured_at', label: 'Vaqt', render: (e) => fmtTime(e.captured_at, app.tz, true) }, { key: 'direction', label: "Yo'n.", render: (e) => (e.direction === 'in' ? '→ kirish' : '← chiqish') },
      { key: 'result', label: 'Natija', render: (e) => statusBadge(e.result) }] })) : null,
    ev.corrections?.length ? h('section', {}, h('h3', {}, 'Tuzatishlar tarixi'), table({ dense: true, rows: ev.corrections, columns: [
      { key: 'kind', label: 'Turi' }, { key: 'status', label: 'Holat', render: (c) => statusBadge(c.status) }, { key: 'requested_by_name', label: "So'ragan" }, { key: 'comment', label: 'Izoh', wrap: true }] })) : null,
  ];
  d.setBody(body);
  const suspicious = ['review', 'pad', 'unknown'].includes(ev.result) || ev.clock_suspect;
  const footer = [];
  if (suspicious && ev.review_status !== 'verified' && ev.review_status !== 'rejected' && app.can('attendance.verify')) {
    footer.push(btn('Rad etish', { variant: 'danger-outline', onClick: () => confirmDanger({
      title: 'Hodisani rad etish', consequences: ['Hodisa ish vaqti hisobidan chiqariladi (asl yozuv saqlanadi)', 'Qaror auditga yoziladi'],
      reasonMin: 10, extra: (() => { const c = checkbox('Xavfsizlik incidentini ochish'); d._incident = c.input; return c; })(), okLabel: 'Rad etish',
      onConfirm: async ({ reason }) => { await app.api.post(`/api/v1/attendance/events/${ev.id}/reject`, { comment: reason, open_incident: !!d._incident?.checked }); toast('Hodisa rad etildi', 'success'); d.close(); onChange?.(); },
    }) }));
    footer.push(btn('Tasdiqlash', { onClick: async () => { if (await act(() => app.api.post(`/api/v1/attendance/events/${ev.id}/verify`, {}), 'Hodisa tasdiqlandi')) { d.close(); onChange?.(); } } }));
  }
  if (ev.employee_id && app.can('correction.request')) footer.unshift(btn('Tuzatish taklif qilish', { variant: 'secondary', onClick: () => { d.close(); openCorrectionDrawer(app, { employee: { id: ev.employee_id, label: `${ev.last_name} ${ev.first_name} · ${ev.personnel_no}` }, work_date: ev.work_date, event: ev }, onChange); } }));
  d.setFooter(footer);

  async function viewCapture() {
    const reason = await new Promise((resolve) => {
      const r = textarea({ rows: 2, placeholder: 'Kamida 10 belgi' });
      const fl = field({ label: "Ko'rish sababi", required: true, input: r });
      const m = modal({ title: "Kadrni ko'rish", body: [h('p', { class: 'muted' }, 'Kadr biometrik ma\'lumot hisoblanadi. Ko\'rish sababi auditga yoziladi.'), fl],
        footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => { m.close(); resolve(null); } }), btn("Ko'rish", { onClick: () => { if (r.value.trim().length < 10) return fl.setError('Kamida 10 belgi'); m.close(); resolve(r.value.trim()); } })] });
    });
    if (!reason) return;
    try { const res = await app.api.post(`/api/v1/attendance/events/${ev.id}/capture`, { reason }); clear(captureBox).appendChild(h('img', { src: res.image_data_url, alt: 'Terminal kadri', style: { maxWidth: '320px', borderRadius: '8px' } })); }
    catch (e) { showError(e); }
  }
}

// ---------------------------------------------------------------- SCR-34 correction drawer
export function openCorrectionDrawer(app, { employee, work_date, event } = {}, onDone) {
  const picker = employeePicker(app, { value: employee || null });
  const date = input({ type: 'date', value: work_date || todayISO(app.tz), max: todayISO(app.tz) });
  const kind = select([['add_event', "Yetishmayotgan kirish/chiqishni qo'shish"], ['change_time', "Vaqtni o'zgartirish"], ['void_event', 'Hodisani hisobdan chiqarish'], ['set_day_status', "Kun holatini o'zgartirish"]], { value: event ? 'change_time' : 'add_event' });
  const direction = select([['in', 'Kirish'], ['out', 'Chiqish']], { value: event?.direction || 'out' });
  const time = input({ type: 'time', value: '' });
  const status = select([['business_trip', 'Xizmat safari'], ['remote', 'Masofaviy ish'], ['present', 'Ishda bo\'lgan'], ['absent', 'Kelmagan']]);
  const reason = select(REASONS);
  const comment = textarea({ rows: 3, placeholder: 'Kamida 15 belgi', maxlength: 1000 });
  const fields = { picker: field({ label: 'Xodim', required: true, input: picker }), date: field({ label: 'Ish kuni', required: true, input: date }), kind: field({ label: 'Turi', required: true, input: kind }),
    direction: field({ label: "Yo'nalish", input: direction }), time: field({ label: 'Yangi vaqt (zavod vaqti)', input: time, help: 'Tungi smenada keyingi kun vaqti uchun sanani +1 qiling' }),
    status: field({ label: 'Kun holati', input: status }), reason: field({ label: 'Sabab', required: true, input: reason }), comment: field({ label: 'Izoh', required: true, input: comment }) };
  const preview = h('div', { class: 'note' }, 'Natija oldindan ko\'rinishi shu yerda chiqadi');
  const sync = () => {
    const k = kind.value;
    fields.direction.hidden = !['add_event', 'change_time'].includes(k);
    fields.time.hidden = !['add_event', 'change_time'].includes(k);
    fields.status.hidden = k !== 'set_day_status';
  };
  kind.addEventListener('change', () => { sync(); doPreview(); }); sync();
  const body = () => {
    const out = { employee_id: picker.value?.id, work_date: date.value, kind: kind.value, reason_code: reason.value, comment: comment.value.trim() };
    if (['add_event', 'change_time'].includes(kind.value) && time.value) { out.new_time = localToUTC(date.value, time.value, app.tz); out.direction = direction.value; }
    if (['change_time', 'void_event'].includes(kind.value)) out.event_id = event?.id || null;
    if (kind.value === 'set_day_status') out.day_status = status.value;
    return out;
  };
  async function doPreview() {
    const b = body();
    if (!b.employee_id || b.comment.length < 15) return;
    try { const p = await app.api.post('/api/v1/attendance/corrections/preview', b, { idempotent: false });
      clear(preview).append(h('strong', {}, 'Natija: '), `${fmtDuration(p.before.worked_min)} → ${fmtDuration(p.after.worked_min)}; `,
        `holat ${p.before.status} → ${p.after.status}`, p.before.late_min !== p.after.late_min ? `; kechikish ${p.before.late_min} → ${p.after.late_min} daq` : '', h('div', { class: 'caption' }, p.after.explanation)); }
    catch (e) { clear(preview).append(errorText(e)); }
  }
  [time, direction, status, date].forEach((el) => el.addEventListener('change', doPreview));
  comment.addEventListener('blur', doPreview);
  const d = drawer({ title: 'Tuzatish so\'rovi', size: 'w720', dirty: () => comment.value.trim().length > 0,
    body: [h('div', { class: 'note' }, "Asl hodisa o'zgarmaydi. Tuzatish boshqa foydalanuvchi tasdiqlagandan keyin kuchga kiradi."),
      h('div', { class: 'form-grid' }, fields.picker, fields.date, fields.kind, fields.reason, fields.direction, fields.time, fields.status, h('div', { class: 'full' }, fields.comment)), preview],
    footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => d.requestClose() }), btn("So'rovni yuborish", { onClick: async () => {
      const b = body(); let ok = true;
      if (!b.employee_id) { fields.picker.setError('Xodimni tanlang'); ok = false; }
      if (b.comment.length < 15) { fields.comment.setError('Kamida 15 belgi'); ok = false; }
      if (['add_event', 'change_time'].includes(b.kind) && !b.new_time) { fields.time.setError('Vaqtni kiriting'); ok = false; }
      if (['change_time', 'void_event'].includes(b.kind) && !b.event_id) { fields.kind.setError('Bu tur uchun hodisani jurnaldan tanlang'); ok = false; }
      if (!ok) return;
      try { const r = await app.api.post('/api/v1/attendance/corrections', b); toast(`So'rov yuborildi. Tasdiqlovchilar: ${r.approvers_notified}`, 'success'); d.close(); onDone?.(); }
      catch (e) {
        if (e.code === 'PERIOD_LOCKED') toast("Bu kun yopilgan davrga tegishli. HR Manager davrni qayta ochishi kerak.", 'error');
        else if (e.code === 'CORRECTION_CONFLICT') toast("Xuddi shunday so'rov allaqachon kutilmoqda", 'warning');
        else showError(e);
      }
    } })] });
  if (event) date.value = event.work_date || date.value;
}

// ---------------------------------------------------------------- SCR-32 timesheet
export async function renderTimesheet(main, params, app) {
  const q = app.query();
  const month = q.month || todayISO(app.tz).slice(0, 7);
  const st = { month, department_id: q.department_id || '', offset: 0, limit: 100 };
  const depts = await departments(app).catch(() => []);
  const monthIn = input({ type: 'month', value: st.month });
  const deptSel = select([['', "Barcha bo'limlar"], ...depts.map((d) => [d.id, d.name])], { value: st.department_id });
  monthIn.addEventListener('change', () => { st.month = monthIn.value; refresh(); });
  deptSel.addEventListener('change', () => { st.department_id = deptSel.value; refresh(); });
  const box = h('div');
  main.append(pageHead('Tabel', 'Kunlik natijalar: katak ustiga bosing — hisoblash izohi', [
    app.can('report.export') ? btn('XLSX eksport', { variant: 'secondary', onClick: async () => { await act(() => app.api.post('/api/v1/reports/export', { type: 'timesheet', format: 'xlsx', params: { month: st.month, department_id: st.department_id || undefined } }), 'Eksport tayyorlanmoqda'); } }) : null]),
    h('div', { class: 'filters' }, field({ label: 'Oy', input: monthIn }), field({ label: "Bo'lim", input: deptSel })),
    h('div', { class: 'legend', style: { marginBottom: '8px' } }, ...[['present', '8:00 ishlangan'], ['late', 'K kechikdi'], ['absent', 'Y kelmadi'], ['leave', "T ta'til"], ['off', 'D dam'], ['incomplete', '? anomaliya']].map(([s, l]) => h('span', { class: `code-cell st-${s}` }, l))), box);
  const CODE = { late: 'K', absent: 'Y', leave: 'T', off: 'D', holiday: 'B', incomplete: '?', business_trip: 'XS', remote: 'M' };
  async function refresh() {
    app.setQuery({ month: st.month, department_id: st.department_id });
    const [y, m] = st.month.split('-').map(Number);
    const from = `${st.month}-01`, to = `${st.month}-${String(new Date(Date.UTC(y, m, 0)).getUTCDate()).padStart(2, '0')}`;
    const end = to > todayISO(app.tz) ? todayISO(app.tz) : to;
    await load(box, () => app.api.get('/api/v1/attendance/daily-summaries', { query: { from, to: end < from ? from : end, department_id: st.department_id || undefined, limit: st.limit, offset: st.offset } }), (r) => {
      const days = daysBetween(from, to);
      const closed = (d) => r.closed_periods.some((p) => p.start_date <= d && p.end_date >= d);
      const tbl = h('table', { class: 'cal-grid' }, h('thead', {}, h('tr', {}, h('th', { style: { textAlign: 'left', padding: '0 10px' } }, 'Xodim'),
        days.map((d) => h('th', { class: [0, 6].includes(weekday(d)) ? 'we' : '' }, h('div', {}, d.slice(8)), h('div', { class: 'caption' }, WEEKDAYS[weekday(d)]), closed(d) ? h('div', { title: 'Davr yopilgan' }, '🔒') : null)),
        h('th', {}, 'Soat'), h('th', {}, "Qo'sh."), h('th', {}, 'K'), h('th', {}, 'Y'))),
      h('tbody', {}, r.employees.map((e) => h('tr', {}, h('td', { class: 'name' }, h('a', { href: `/app/employees/${e.id}`, 'data-link': '' }, `${e.last_name} ${e.first_name}`), h('div', { class: 'caption' }, `${e.personnel_no} · ${e.department_name || ''}`)),
        days.map((d) => {
          const s = r.days[e.id]?.[d];
          if (!s) return h('td', { class: [0, 6].includes(weekday(d)) ? 'we' : '' });
          const label = s.worked_min && !['leave'].includes(s.status) ? `${CODE[s.status] ? CODE[s.status] + ' ' : ''}${Math.floor(s.worked_min / 60)}:${String(s.worked_min % 60).padStart(2, '0')}` : (CODE[s.status] || '');
          const td = h('td', { class: 'cell', tabIndex: 0, title: s.explanation }, h('span', { class: `code-cell st-${s.status}` }, label));
          const open = () => popover(td, h('div', { class: 'stack small' }, h('strong', {}, `${e.last_name} ${e.first_name} · ${fmtDate(d)}`), statusBadge(s.status), h('div', {}, s.explanation),
            s.anomalies.length ? h('div', { class: 'note warning' }, `Anomaliya: ${s.anomalies.join(', ')}`) : null, s.corrected ? badge('Tuzatilgan', 'info', '✎') : null,
            h('div', { class: 'row' }, btn('Hodisalar', { variant: 'tertiary', size: 's', onClick: () => app.go(`/attendance/events?employee_id=${e.id}&from=${d}&to=${addDays(d, 1)}`) }),
              app.can('correction.request') && !closed(d) ? btn('Tuzatish', { variant: 'secondary', size: 's', onClick: () => openCorrectionDrawer(app, { employee: { id: e.id, label: `${e.last_name} ${e.first_name}` }, work_date: d }, refresh) }) : null)));
          td.addEventListener('click', open); td.addEventListener('keydown', (ev) => ev.key === 'Enter' && open());
          return td;
        }),
        h('td', { class: 'tabular' }, (r.totals[e.id].worked_min / 60).toFixed(1)), h('td', { class: 'tabular' }, (r.totals[e.id].overtime_min / 60).toFixed(1)),
        h('td', {}, r.totals[e.id].late_count), h('td', {}, r.totals[e.id].absent_count)))));
      return [r.employees.length ? h('div', { class: 'table-wrap' }, tbl) : emptyState({ title: 'Xodimlar topilmadi' }),
        pagination({ total: r.total, limit: st.limit, offset: st.offset, sizes: [50, 100, 200], onChange: (p) => { Object.assign(st, p); refresh(); } })];
    });
  }
  await refresh();
}

// ---------------------------------------------------------------- SCR-33 anomalies
const ANOMALY = { missing_out: 'Chiqish qayd etilmagan', missing_in: 'Kirish qayd etilmagan', review_required: 'Tekshiruv kerak', late_event_after_close: 'Yopilgan davrga kech hodisa', clock_suspect: 'Soat shubhali' };
export async function renderAnomalies(main, params, app) {
  const st = { status: app.query().status || 'open', limit: 50, offset: 0 };
  const tabBox = h('div'), box = h('div');
  main.append(pageHead('Anomaliyalar', "Hal qilinmaguncha tabel to'liq emas — tuzatish yoki tekshiruv orqali yoping"), tabBox, box);
  async function refresh() {
    clear(tabBox).appendChild(tabs([{ key: 'open', label: 'Ochiq' }, { key: 'resolved', label: 'Hal qilingan' }], st.status, (k) => { st.status = k; st.offset = 0; refresh(); }));
    await load(box, () => app.api.get('/api/v1/attendance/anomalies', { query: st }), (r) => [table({
      rows: r.items, empty: emptyState({ icon: '✓', title: "Ochiq anomaliya yo'q" }),
      columns: [{ key: 'work_date', label: 'Sana', render: (a) => fmtDate(a.work_date) }, { key: 'name', label: 'Xodim', render: (a) => `${a.last_name} ${a.first_name} · ${a.personnel_no}` },
        { key: 'department_name', label: "Bo'lim" }, { key: 'kind', label: 'Turi', render: (a) => badge(ANOMALY[a.kind] || a.kind, 'warning') },
        { key: 'act', label: '', render: (a) => (st.status === 'open' ? h('span', { class: 'row' },
          app.can('correction.request') && ['missing_out', 'missing_in'].includes(a.kind) ? btn('Tuzatish', { variant: 'secondary', size: 's', onClick: () => openCorrectionDrawer(app, { employee: { id: a.employee_id, label: `${a.last_name} ${a.first_name}` }, work_date: a.work_date }, refresh) }) : null,
          btn('Hodisalar', { variant: 'tertiary', size: 's', onClick: () => app.go(`/attendance/events?employee_id=${a.employee_id}&from=${a.work_date}&to=${addDays(a.work_date, 1)}`) }),
          a.kind === 'late_event_after_close' && app.can('correction.request') ? btn('Hal qilindi', { variant: 'tertiary', size: 's', onClick: async () => { if (await act(() => app.api.post(`/api/v1/attendance/anomalies/${a.id}/resolve`, { comment: 'ko\'rib chiqildi' }), 'Belgilandi')) refresh(); } }) : null) : '') }] }),
    pagination({ total: r.total, limit: st.limit, offset: st.offset, onChange: (p) => { Object.assign(st, p); refresh(); } })]);
  }
  await refresh();
}

// ---------------------------------------------------------------- SCR-35 approvals
export async function renderApprovals(main, params, app) {
  const box = h('div'), bulk = h('div');
  const selected = new Set();
  let tab = 'all';
  const tabBox = h('div');
  main.append(pageHead('Tasdiqlar', "Tuzatishlar, xodim e'tirozlari va ta'til so'rovlari · o'z so'rovingizni tasdiqlay olmaysiz"), tabBox, bulk, box);
  async function decide(item, approve) {
    const base = item.type === 'leave' ? `/api/v1/leaves/${item.id}` : `/api/v1/attendance/corrections/${item.id}`;
    if (approve) { if (await act(() => app.api.post(`${base}/approve`, {}), 'Tasdiqlandi')) refresh(); return; }
    await confirmDanger({ title: 'Rad etish', reasonMin: 10, okLabel: 'Rad etish', onConfirm: async ({ reason }) => { await app.api.post(`${base}/reject`, { comment: reason }); toast('Rad etildi', 'success'); refresh(); } });
  }
  async function refresh() {
    selected.clear(); clear(bulk);
    await load(box, () => app.api.get('/api/v1/approvals'), (r) => {
      clear(tabBox).appendChild(tabs([{ key: 'all', label: 'Hammasi', count: r.items.length }, { key: 'correction', label: 'Tuzatishlar', count: r.counts.correction }, { key: 'dispute', label: "E'tirozlar", count: r.counts.dispute }, { key: 'leave', label: "Ta'til", count: r.counts.leave }], tab, (k) => { tab = k; refresh(); }));
      const rows = r.items.filter((i) => tab === 'all' || i.type === tab);
      const showBulk = () => {
        clear(bulk);
        const ids = [...selected].filter((id) => rows.find((x) => x.id === id && x.type !== 'leave' && !x.own));
        if (!selected.size) return;
        bulk.appendChild(h('div', { class: 'bulk-bar' }, `${selected.size} ta tanlandi`, ids.length !== selected.size ? h('span', { class: 'caption' }, `(${selected.size - ids.length} tasi o'zingizniki yoki ta'til — o'tkazib yuboriladi)`) : null,
          btn('Ommaviy tasdiqlash', { variant: 'secondary', size: 's', onClick: async () => { const res = await act(() => app.api.post('/api/v1/attendance/corrections/bulk-approve', { ids })); if (res) { toast(`${res.approved} tasdiqlandi, ${res.skipped.length} o'tkazib yuborildi`, 'success'); refresh(); } } })));
      };
      return table({ rows, selectable: app.can('correction.approve'), selected, onSelect: showBulk, empty: emptyState({ icon: '✓', title: "Tasdiq kutayotgan so'rov yo'q" }), columns: [
        { key: 'type', label: 'Turi', render: (i) => badge({ correction: 'Tuzatish', dispute: "E'tiroz", leave: "Ta'til" }[i.type], i.type === 'dispute' ? 'purple' : i.type === 'leave' ? 'info' : 'primary') },
        { key: 'employee', label: 'Xodim', render: (i) => `${i.employee} · ${i.personnel_no}` }, { key: 'date', label: 'Sana', render: (i) => (i.end_date && i.end_date !== i.date ? `${fmtDate(i.date)} – ${fmtDate(i.end_date)}` : fmtDate(i.date)) },
        { key: 'kind', label: 'Mazmun' }, { key: 'comment', label: 'Izoh', wrap: true }, { key: 'requested_by', label: "So'ragan" },
        { key: 'sla_due', label: 'SLA', render: (i) => (i.sla_due ? (new Date(i.sla_due) < new Date() ? badge('Muddati o\'tgan', 'danger') : fmtDate(i.sla_due, app.tz)) : '—') },
        { key: 'act', label: '', render: (i) => (i.own ? h('span', { class: 'caption', title: "O'z so'rovingizni tasdiqlay olmaysiz" }, "o'zingizniki") : h('span', { class: 'row' },
          btn('Rad etish', { variant: 'danger-outline', size: 's', onClick: () => decide(i, false) }), btn('Tasdiqlash', { size: 's', onClick: () => decide(i, true) }))) }] });
    });
  }
  await refresh();
}

// ---------------------------------------------------------------- SCR-36 periods
export async function renderPeriods(main, params, app) {
  const box = h('div');
  const tree = await app.api.get('/api/v1/org/tree').catch(() => ({ sites: [] }));
  main.append(pageHead('Davrlar', "Yopilgan davr muzlatiladi: payroll eksportdan keyin o'zgarmaydi", [app.can('period.close') ? btn('Yangi davr', { onClick: () => newPeriod() }) : null]), box);
  function newPeriod() {
    const site = select(tree.sites.map((s) => [s.id, s.name]));
    const today = todayISO(app.tz);
    const first = `${today.slice(0, 7)}-01`;
    const prevFirst = addDays(first, -1).slice(0, 7) + '-01';
    const start = input({ type: 'date', value: prevFirst }), end = input({ type: 'date', value: addDays(first, -1) });
    const m = modal({ title: 'Yangi davr', body: [field({ label: 'Zavod', input: site }), h('div', { class: 'form-grid' }, field({ label: 'Boshlanish', input: start }), field({ label: 'Tugash', input: end }))],
      footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn('Yaratish', { onClick: async () => { if (await act(() => app.api.post('/api/v1/attendance/periods', { site_id: site.value, start_date: start.value, end_date: end.value }), 'Davr yaratildi')) { m.close(); refresh(); } } })] });
  }
  async function closePeriod(p) {
    let cl;
    try { cl = (await app.api.get(`/api/v1/attendance/periods/${p.id}/checklist`)).checklist; } catch (e) { showError(e); return; }
    const labels = { open_anomalies: 'Ochiq anomaliyalar', pending_corrections: 'Kutilayotgan tuzatishlar', pending_leaves: "Kutilayotgan ta'tillar", pending_reviews: 'Tekshirilmagan hodisalar', offline_devices: 'Offline qurilmalar' };
    const open = Object.values(cl).some(Boolean);
    const note = textarea({ rows: 2, placeholder: open ? 'Ochiq elementlar bilan yopish sababi (kamida 10 belgi)' : 'Ixtiyoriy izoh' });
    const m = modal({ title: `Davrni yopish: ${fmtDate(p.start_date)} – ${fmtDate(p.end_date)}`, size: 'w640', body: [
      h('ul', { class: 'checklist' }, Object.entries(cl).map(([k, v]) => h('li', {}, h('span', { class: v ? 'warn' : 'ok' }, v ? '⚠' : '✓'), `${labels[k]}: ${v}`))),
      open ? h('div', { class: 'note warning' }, "Ochiq elementlar bor. Ularni hal qilish tavsiya etiladi; baribir yopsangiz, sabab majburiy.") : h('div', { class: 'note success' }, 'Hammasi tayyor.'),
      h('div', { class: 'consequences' }, h('strong', {}, 'Oqibatlar:'), h('ul', {}, h('li', {}, 'Kunlik natijalar muzlatiladi'), h('li', {}, 'Bu davrga tuzatish faqat davr qayta ochilgach mumkin (ikki HR Manager)'), h('li', {}, 'Kech kelgan hodisalar alohida navbatga tushadi'))),
      field({ label: 'Izoh', input: note })],
      footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn(open ? 'Baribir yopish' : 'Davrni yopish', { onClick: async () => {
        if (open && note.value.trim().length < 10) { toast('Sabab kamida 10 belgi', 'warning'); return; }
        if (await act(() => app.api.post(`/api/v1/attendance/periods/${p.id}/close`, { force: open, note: note.value.trim() || null }), 'Davr yopildi. Payroll eksportga tayyor.')) { m.close(); refresh(); }
      } })] });
  }
  async function refresh() {
    await load(box, () => app.api.get('/api/v1/attendance/periods'), (r) => table({ rows: r.items, empty: emptyState({ icon: '🔒', title: "Davrlar yo'q", text: "Oylik davr yarating va oy oxirida yoping" }), columns: [
      { key: 'site_name', label: 'Zavod' }, { key: 'range', label: 'Davr', render: (p) => `${fmtDate(p.start_date)} – ${fmtDate(p.end_date)}` },
      { key: 'status', label: 'Holat', render: (p) => statusBadge(p.status) }, { key: 'closed_by_name', label: 'Yopgan' }, { key: 'closed_at', label: 'Yopilgan', render: (p) => fmtDateTime(p.closed_at, app.tz) },
      { key: 'act', label: '', render: (p) => h('span', { class: 'row' },
        p.status === 'open' && app.can('period.close') ? btn('Davrni yopish', { size: 's', onClick: () => closePeriod(p) }) : null,
        p.status === 'closed' && app.can('period.close') ? btn('Payroll eksport', { variant: 'secondary', size: 's', onClick: () => act(() => app.api.post('/api/v1/reports/export', { type: 'payroll', format: 'csv', params: { from: p.start_date, to: p.end_date, site_id: p.site_id } }), 'Eksport tayyorlanmoqda') }) : null,
        p.status === 'closed' && app.can('period.reopen') ? btn('Qayta ochish', { variant: 'danger-outline', size: 's', onClick: () => confirmDanger({ title: 'Davrni qayta ochish so\'rovi', consequences: ['Ikkinchi HR Manager tasdig\'i kerak', 'Payroll qayta eksport qilinishi kerak bo\'ladi'], reasonMin: 10, okLabel: "So'rov yuborish", onConfirm: async ({ reason }) => { await app.api.post(`/api/v1/attendance/periods/${p.id}/reopen-request`, { reason }); toast('So\'rov yuborildi', 'success'); refresh(); } }) }) : null,
        p.status === 'reopen_requested' && app.can('period.reopen') ? btn('Qayta ochishni tasdiqlash', { variant: 'secondary', size: 's', onClick: async () => { if (await act(() => app.api.post(`/api/v1/attendance/periods/${p.id}/reopen-approve`), 'Davr ochildi')) refresh(); } }) : null,
        p.status === 'reopen_requested' && app.can('period.reopen') ? btn('Bekor qilish', { variant: 'tertiary', size: 's', onClick: async () => { if (await act(() => app.api.post(`/api/v1/attendance/periods/${p.id}/reopen-cancel`))) refresh(); } }) : null) }] }));
  }
  await refresh();
}
