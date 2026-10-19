// SCR-50 … SCR-52 reports & exports; ROI dashboard.
import { h, clear, btn, select, input, field, table, toast, statusBadge, emptyState, load, kv, menu, showError, form, errorState } from '/assets/core/ui.js';
import { fmtDateTime, todayISO, addDays, fmtMoney } from '/assets/core/format.js';
import { pageHead, departments, act } from './common.js';

const GROUPS = { attendance: 'Davomat', time: 'Vaqt', absence: "Yo'qliklar", devices: 'Qurilmalar', security: 'Xavfsizlik' };

export async function renderCatalog(main, params, app) {
  const box = h('div');
  main.append(pageHead('Hisobotlar', null, [btn('Eksportlar tarixi', { variant: 'secondary', onClick: () => app.go('/reports/exports') })]), box);
  await load(box, () => app.api.get('/api/v1/reports'), (r) => Object.entries(GROUPS).map(([g, label]) => {
    const items = r.items.filter((x) => x.group === g && x.allowed);
    if (!items.length) return null;
    return h('section', { style: { marginBottom: '20px' } }, h('h2', {}, label), h('div', { class: 'grid cols-3' }, items.map((it) => h('a', { class: 'card', href: `/app/reports/${it.type}`, 'data-link': '', style: { color: 'inherit', display: 'block' } },
      h('h3', {}, it.name), h('div', { class: 'caption' }, `Parametrlar: ${it.params.join(', ')}`), h('div', { class: 'caption' }, it.last_run_at ? `Oxirgi eksport: ${fmtDateTime(it.last_run_at, app.tz)}` : '')))));
  }));
}

export async function renderReport(main, params, app) {
  const cat = await app.api.get('/api/v1/reports');
  const spec = cat.items.find((x) => x.type === params.type);
  if (!spec) { main.appendChild(emptyState({ title: 'Hisobot topilmadi' })); return; }
  const depts = await departments(app).catch(() => []);
  const today = todayISO(app.tz);
  const p = { date: input({ type: 'date', value: today, max: today }), month: input({ type: 'month', value: today.slice(0, 7) }),
    from: input({ type: 'date', value: addDays(today, -30) }), to: input({ type: 'date', value: today, max: today }) };
  const dept = select([['', "Barcha bo'limlar"], ...depts.map((d) => [d.id, d.name])]);
  const team = select([['', 'Barcha brigadalar'], ['A', 'A'], ['B', 'B'], ['C', 'C'], ['D', 'D']]);
  const out = h('div');
  const values = () => { const v = { department_id: dept.value || undefined, team: team.value || undefined }; spec.params.forEach((k) => { v[k] = p[k].value; }); return v; };
  const run = btn('Ishga tushirish', { onClick: async () => {
    await load(out, () => app.api.post('/api/v1/reports/run', { type: spec.type, params: values() }, { idempotent: false }), (r) => [
      h('div', { class: 'row', style: { margin: '8px 0' } }, h('strong', {}, r.title), h('span', { class: 'caption' }, `${r.row_count} qator`), r.period_status ? statusBadge(r.period_status === 'closed' ? 'closed' : 'open') : null,
        r.period_status === 'open' ? h('span', { class: 'caption' }, "Davr yopilmagan — raqamlar o'zgarishi mumkin") : null),
      r.legend ? h('div', { class: 'caption', style: { marginBottom: '6px' } }, r.legend) : null,
      table({ dense: true, rows: r.rows.map((row, i) => ({ id: i, row })), columns: r.columns.map((c, i) => ({ key: String(i), label: c, render: (x) => String(x.row[i] ?? '') })), empty: emptyState({ title: "Ma'lumot yo'q" }) })]);
  } });
  const exp = app.can('report.export') ? btn('Eksport ▾', { variant: 'secondary', onClick: () => menu(exp, ['xlsx', 'csv', 'pdf'].map((fmt) => ({ label: fmt.toUpperCase(), onClick: async () => {
    try { await app.api.post('/api/v1/reports/export', { type: spec.type, format: fmt, params: values() }); toast('Eksport tayyorlanmoqda. Tayyor bo\'lganda bildirishnoma keladi.', 'info'); }
    catch (e) { showError(e); }
  } }))) }) : null;
  main.append(pageHead(spec.name, null, [run, exp], [['Hisobotlar', '/reports'], [spec.name]]),
    h('div', { style: { display: 'grid', gridTemplateColumns: 'minmax(240px, 320px) 1fr', gap: '16px' }, class: 'profile-grid' },
      h('div', { class: 'card stack' }, h('h3', {}, 'Parametrlar'), spec.params.map((k) => field({ label: { date: 'Sana', month: 'Oy', from: 'Dan', to: 'Gacha' }[k], input: p[k] })),
        field({ label: "Bo'lim", input: dept }), field({ label: 'Brigada', input: team })), h('div', { class: 'card' }, out)));
  out.appendChild(emptyState({ icon: '📊', title: 'Parametrlarni tanlang va "Ishga tushirish" ni bosing' }));
}

export async function renderExports(main, params, app) {
  const box = h('div');
  main.append(pageHead('Eksportlar', 'Fayllar 7 kun saqlanadi; har yuklab olish auditga yoziladi', [btn('Yangilash', { variant: 'secondary', onClick: () => refresh() })], [['Hisobotlar', '/reports'], ['Eksportlar']]), box);
  async function refresh() {
    await load(box, () => app.api.get('/api/v1/exports'), (r) => table({ rows: r.items, empty: emptyState({ title: "Eksportlar yo'q" }), columns: [
      { key: 'created_at', label: 'Vaqt', render: (e) => fmtDateTime(e.created_at, app.tz) }, { key: 'kind', label: 'Hisobot' }, { key: 'format', label: 'Format', render: (e) => e.format.toUpperCase() },
      { key: 'rows', label: 'Qatorlar', num: true }, { key: 'requested_by_name', label: "So'ragan" }, { key: 'status', label: 'Holat', render: (e) => statusBadge(e.status) },
      { key: 'act', label: '', render: (e) => (e.status === 'ready' ? btn('Yuklab olish', { variant: 'secondary', size: 's', onClick: () => app.api.download(`/api/v1/exports/${e.id}/download`).catch(showError) }) : e.error ? h('span', { class: 'caption' }, e.error) : '') }] }));
  }
  await refresh();
  const t = setInterval(() => { if (!document.body.contains(box)) clearInterval(t); else refresh(); }, 5000);
}

// ---------------------------------------------------------------- ROI dashboard (business tab 5.5, SCR-R2)
export async function renderRoi(main, params, app) {
  const box = h('div');
  main.append(pageHead('ROI dashboard', "O'lchangan qiymatlar tizimdan; baza va taxminlar alohida belgilanadi"), box);
  async function refresh() {
    await load(box, () => app.api.get('/api/v1/roi/dashboard'), (r) => {
      const m = r.measured;
      const est = r.estimate;
      return [h('div', { class: 'grid cols-3' },
        h('div', { class: 'card' }, h('h3', {}, "O'lchangan (30 kun)"), kv([['Hodisalar', m.events_30d], ['Tuzatishlar', m.corrections_30d], ["Xodim e'tirozlari", m.disputes_30d], ["To'xtatilgan shubhali urinishlar", m.blocked_attempts_30d], ["Qo'shimcha ish (soat)", m.overtime_hours_30d], ['Kechikishlar (daq)', m.late_minutes_30d]])),
        h('div', { class: 'card' }, h('h3', {}, 'Bazaviy hisob-kitob'), est ? kv([['Hozirgi xarajat / oy', `$${est.cost_now_monthly}`], ['Tizimdan keyin / oy', `$${est.cost_after_monthly}`], ['Oylik sof tejam', `$${est.net_saving_monthly}`], ['Qoplanish', est.payback_months ? `${est.payback_months} oy` : 'qoplanmaydi']]) : emptyState({ title: 'Baza kiritilmagan' })),
        h('div', { class: 'card stack' }, h('h3', {}, 'Taxminlar'), est ? [...est.assumptions.map((a) => h('div', { class: 'note warning small' }, a.text)), ...est.excluded.map((x) => h('div', { class: 'note small' }, x))] : null, h('div', { class: 'caption' }, r.note))),
      h('div', { class: 'card', style: { marginTop: '16px' } }, h('h3', {}, 'Bazaviy qiymatlar (onboarding paytida)'), baselineForm(r.baseline))];
    });
  }
  function baselineForm(base) {
    const f = form([
      { name: 'employees', label: 'Faol xodimlar', type: 'number', required: true }, { name: 'payroll_monthly', label: "Oylik ish haqi fondi ($)", type: 'number', required: true },
      { name: 'hr_hour_cost', label: 'HR 1 soat narxi ($)', type: 'number', required: true }, { name: 'hr_hours_now', label: 'Tabelga HR vaqti (soat/oy)', type: 'number', required: true },
      { name: 'fix_hours_now', label: 'Tuzatish/nizolar (soat/oy)', type: 'number', required: true }, { name: 'leakage_pct_now', label: "Ortiqcha to'lov ulushi (%)", type: 'number', step: '0.01', help: "Bo'sh qoldirsangiz natijaga kirmaydi" },
      { name: 'subscription_monthly', label: 'Obuna ($/oy)', type: 'number', required: true }, { name: 'devices_cost', label: 'Qurilmalar ($)', type: 'number', required: true },
      { name: 'install_cost', label: "O'rnatish ($)", type: 'number', required: true }, { name: 'integration_cost', label: 'Integratsiya ($)', type: 'number' },
    ], base || {});
    return h('div', { class: 'stack' }, f.el, h('div', { class: 'btn-bar' }, btn('Saqlash', { onClick: async () => {
      if (!f.validate()) return;
      const v = f.values(); for (const k of Object.keys(v)) if (v[k] === null) delete v[k];
      if (await act(() => app.api.put('/api/v1/roi/baseline', { inputs: v }), 'Saqlandi', f)) refresh();
    } })));
  }
  await refresh();
}

export { fmtMoney, errorState };
