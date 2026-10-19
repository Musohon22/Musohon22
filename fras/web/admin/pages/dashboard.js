// SCR-01 Admin Dashboard and SCR-02 live feed.
import { h, clear, btn, select, input, field, drawer, toast, errorState, emptyState, skeletonRows, statusBadge, table, debounce } from '/assets/core/ui.js';
import { fmtTime, fmtDateTime, todayISO, initials, relTime } from '/assets/core/format.js';
import { openEventDrawer } from './attendance.js';
import { pageHead } from './common.js';


export async function render(main, params, app) {
  const q = app.query();
  const state = { date: q.date || todayISO(app.tz), site_id: app.site || q.site_id || '', department_id: q.department_id || '', shift_code: q.shift_code || '' };
  const updated = h('span', { class: 'tabular' }, '—');
  const live = h('span', { class: 'row caption' }, h('span', { class: 'dot live' }), 'Jonli · ', 'Ma\'lumot: ', updated, ' holatida');
  const kpiBox = h('div', { class: 'grid cols-6' });
  const chartBox = h('div', { class: 'card' });
  const deptBox = h('div', { class: 'card' });
  const feedBox = h('div', { class: 'card' });
  const attentionBox = h('div', { class: 'card' });
  const devicesBox = h('div', { class: 'card' });
  const warning = h('div');

  let tree = { sites: [] };
  try { tree = await app.api.get('/api/v1/org/tree'); } catch { /* scope */ }
  const depts = tree.sites.flatMap((s) => s.departments);
  let templates = [];
  try { templates = (await app.api.get('/api/v1/shifts/templates')).items; } catch { /* ignore */ }
  const dateIn = input({ type: 'date', value: state.date, max: todayISO(app.tz) });
  const siteSel = select([['', 'Barcha zavodlar'], ...tree.sites.map((s) => [s.id, s.name])], { value: state.site_id });
  if (tree.sites.length <= 1) siteSel.disabled = true;
  const deptSel = select([['', "Barcha bo'limlar"], ...depts.map((d) => [d.id, d.name])], { value: state.department_id });
  const shiftSel = select([['', 'Barcha smenalar'], ...templates.map((t) => [t.code, `${t.code} · ${t.start_time}–${t.end_time}`])], { value: state.shift_code });
  const clearBtn = btn('Tozalash', { variant: 'tertiary', size: 's', onClick: () => { Object.assign(state, { date: todayISO(app.tz), department_id: '', shift_code: '' }); dateIn.value = state.date; deptSel.value = ''; shiftSel.value = ''; refresh(); } });
  for (const [el, key] of [[dateIn, 'date'], [siteSel, 'site_id'], [deptSel, 'department_id'], [shiftSel, 'shift_code']]) el.addEventListener('change', () => { state[key] = el.value; refresh(); });

  let lastRefresh = 0;
  const refreshBtn = btn('Yangilash', { variant: 'secondary', icon: '↻', onClick: () => { if (Date.now() - lastRefresh > 5000) return refresh(); } });
  const exportBtn = app.can('report.export') ? btn('Eksport', { variant: 'secondary', onClick: async () => {
    try { await app.api.post('/api/v1/reports/export', { type: 'daily', format: 'xlsx', params: { date: state.date, site_id: state.site_id || undefined, department_id: state.department_id || undefined } });
      toast('Eksport tayyorlanmoqda. Tayyor bo\'lganda bildirishnoma keladi.', 'info'); }
    catch (e) { toast(e.message, 'error'); }
  } }) : null;

  main.append(pageHead('Dashboard', null, [refreshBtn, exportBtn]), live,
    h('div', { class: 'filters' }, field({ label: 'Sana', input: dateIn }), field({ label: 'Zavod', input: siteSel }),
      field({ label: "Bo'lim", input: deptSel }), field({ label: 'Smena', input: shiftSel }), clearBtn),
    warning, kpiBox, h('div', { style: { height: '16px' } }),
    h('div', { class: 'split' }, h('div', { class: 'stack' }, chartBox, deptBox), feedBox), h('div', { style: { height: '16px' } }),
    h('div', { class: 'grid cols-2' }, attentionBox, devicesBox));

  const filters = () => ({ date: state.date, site_id: state.site_id || undefined, department_id: state.department_id || undefined, shift_code: state.shift_code || undefined });

  function kpi(label, value, sub, cls, onClick, extra) {
    return h('button', { class: `kpi ${cls || ''}`, onclick: onClick, 'aria-label': `${label}: ${value}` },
      h('div', { class: 'label' }, label, extra || null), h('div', { class: 'value' }, value), h('div', { class: 'sub' }, sub || ''));
  }
  function diff(now, prev) { if (prev === undefined) return ''; const d = now - prev; return `kecha bilan ${d >= 0 ? '+' : ''}${d}`; }

  async function refresh() {
    lastRefresh = Date.now();
    app.setQuery({ date: state.date, department_id: state.department_id, shift_code: state.shift_code });
    if (!kpiBox.children.length) kpiBox.append(...Array.from({ length: 6 }, () => h('div', { class: 'kpi' }, h('div', { class: 'skeleton', style: { width: '60%' } }), h('div', { class: 'skeleton', style: { height: '32px', width: '40%' } }))));
    try {
      const [s, arr, dep, att] = await Promise.all([
        app.api.get('/api/v1/dashboard/summary', { query: filters() }),
        app.api.get('/api/v1/dashboard/arrivals', { query: filters() }),
        app.api.get('/api/v1/dashboard/departments', { query: filters() }),
        app.api.get('/api/v1/dashboard/attention'),
      ]);
      const k = s.kpi;
      clear(kpiBox).append(
        kpi('Kelganlar', k.arrived.value, `${k.arrived.value} / ${k.arrived.expected}${k.arrived.expected ? ` · ${(100 * k.arrived.value / k.arrived.expected).toFixed(1)}%` : ''}`, '', () => listDrawer('arrived')),
        kpi('Kechikkanlar', k.late.value, diff(k.late.value, k.late.yesterday), k.late.value ? 'warn' : '', () => listDrawer('late')),
        kpi('Hozir ishda', k.in_now.value, 'oxirgi hodisa — kirish', '', () => listDrawer('in_now')),
        kpi('Kelmaganlar', k.absent.value, diff(k.absent.value, k.absent.yesterday), k.absent.value ? 'danger' : '', () => listDrawer('absent'),
          k.absent.approximate ? h('span', { class: 'badge warning', title: "Offline qurilmalar bor — son taxminiy" }, 'taxminiy') : null),
        kpi("Ta'til/kasal", k.leave.value, '', '', () => listDrawer('leave')),
        kpi('Qurilmalar', `${k.devices.online}/${k.devices.total}`, k.devices.offline ? `${k.devices.offline} ta offline` : 'hammasi ishlayapti', k.devices.offline ? 'danger' : '', () => app.go('/devices')));
      clear(warning);
      if (k.devices.offline) warning.appendChild(h('div', { class: 'note warning', style: { marginBottom: '12px' } }, `${k.devices.offline} ta qurilma offline — ularning hodisalari kechikib kelishi mumkin. `, h('a', { href: '/app/devices?status=offline', 'data-link': '' }, "Qurilmalarni ko'rish")));
      renderChart(arr); renderDepts(dep.items); renderAttention(att);
      updated.textContent = fmtTime(new Date().toISOString(), app.tz, true);
    } catch (e) { clear(kpiBox).appendChild(errorState(e, refresh)); }
  }

  function renderChart(arr) {
    clear(chartBox);
    const max = Math.max(1, ...arr.hours.map((x) => x.in + x.out));
    const starts = new Set(arr.shift_starts.map((s) => Number(s.start_time.slice(0, 2))));
    chartBox.append(h('h3', {}, 'Soat bo\'yicha kirish va chiqish', h('span', { class: 'right legend' }, h('span', {}, '■ kirish'), h('span', { style: { color: 'var(--n-300)' } }, '■ chiqish'))),
      h('div', { class: 'bars', role: 'img', 'aria-label': 'Soatlar bo\'yicha kirishlar diagrammasi' }, arr.hours.map((x) => h('div', { style: { flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: '100%', borderLeft: starts.has(x.hour) ? '2px dashed var(--c-warning)' : 'none' } },
        h('div', { class: 'bar out', style: { height: `${(x.out / max) * 100}%` }, 'data-tip': `${String(x.hour).padStart(2, '0')}:00 chiqish ${x.out}` }),
        h('div', { class: 'bar', style: { height: `${(x.in / max) * 100}%` }, 'data-tip': `${String(x.hour).padStart(2, '0')}:00 kirish ${x.in}` })))),
      h('div', { class: 'axis' }, arr.hours.map((x) => h('span', {}, x.hour % 3 === 0 ? String(x.hour).padStart(2, '0') : ''))),
      h('div', { class: 'caption', style: { marginTop: '6px' } }, 'Uzuq chiziq — smena boshlanishi'));
  }

  function renderDepts(items) {
    clear(deptBox).append(h('h3', {}, "Bo'limlar kesimida", h('span', { class: 'right caption' }, 'kelgan / kutilgan')));
    if (!items.length) { deptBox.appendChild(emptyState({ title: "Bu kunda smena rejalashtirilmagan", action: app.can('shift.assign') ? btn('Jadvalni ochish', { variant: 'secondary', onClick: () => app.go('/shifts/schedule') }) : null })); return; }
    for (const d of items) {
      const exp = d.expected || 0, arrived = d.arrived || 0, late = d.late || 0;
      deptBox.appendChild(h('div', { class: 'hbar' }, h('span', { title: d.name, style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, d.name),
        h('div', { class: 'track', title: `kelgan ${arrived}, kechikkan ${late}, kutilgan ${exp}` },
          h('div', { class: 'fill', style: { width: `${exp ? ((arrived - late) / exp) * 100 : 0}%` } }),
          h('div', { class: 'fill late', style: { width: `${exp ? (late / exp) * 100 : 0}%` } })),
        h('span', { class: 'tabular small' }, `${arrived} / ${exp}`)));
    }
  }

  function renderAttention(att) {
    clear(attentionBox).append(h('h3', {}, 'Diqqat talab qiladi'));
    const items = [
      ['Ochiq anomaliyalar', att.anomalies, '/attendance/anomalies'],
      att.approvals !== undefined ? ['Tasdiq kutayotgan tuzatishlar', att.approvals, '/approvals'] : null,
      att.leaves !== undefined ? ["Ta'til so'rovlari", att.leaves, '/approvals'] : null,
      att.duplicate_faces !== undefined ? ["Dublikat yuz ko'rib chiqish", att.duplicate_faces, '/biometrics/reviews'] : null,
      att.alerts !== undefined ? ['Yangi xavfsizlik ogohlantirishlari', att.alerts, '/security/alerts'] : null,
    ].filter(Boolean);
    for (const [label, n, path] of items) {
      attentionBox.appendChild(h('div', { class: 'row', style: { padding: '8px 0', borderBottom: '1px solid var(--border)' } },
        h('span', { class: `badge ${n ? 'warning' : ''}` }, n), h('span', { style: { flex: 1 } }, label), btn('Ochish', { variant: 'tertiary', size: 's', onClick: () => app.go(path) })));
    }
    clear(devicesBox).append(h('h3', {}, 'Qurilmalar holati'));
    if (!att.offline_devices) { devicesBox.appendChild(h('div', { class: 'muted' }, "Qurilmalarni ko'rish ruxsati yo'q")); return; }
    if (!att.offline_devices.length) { devicesBox.appendChild(h('div', { class: 'note success' }, '✓ Barcha qurilmalar online')); return; }
    devicesBox.appendChild(table({ dense: true, rows: att.offline_devices, onRow: (d) => app.go(`/devices/${d.id}`), columns: [
      { key: 'name', label: 'Qurilma' }, { key: 'last_seen_at', label: 'Oxirgi aloqa', render: (d) => relTime(d.last_seen_at) },
      { key: 'outbox_size', label: 'Navbatda', num: true }] }));
  }

  async function listDrawer(kind) {
    const titles = { arrived: 'Kelganlar', late: 'Kechikkanlar', in_now: 'Hozir ishda', absent: 'Kelmaganlar', leave: "Ta'til/kasal" };
    const d = drawer({ title: titles[kind], body: skeletonRows(6, 3), size: 'w720' });
    try {
      const s = await app.api.get('/api/v1/attendance/daily-summaries', { query: { from: state.date, to: state.date, site_id: state.site_id || undefined, department_id: state.department_id || undefined, limit: 500 } });
      const rows = s.employees.map((e) => ({ ...e, s: s.days[e.id]?.[state.date] })).filter((r) => {
        const st = r.s; if (!st) return false;
        return { arrived: !!st.first_in, late: st.late_min > 0, in_now: st.first_in && !st.last_out, absent: st.status === 'absent', leave: st.status === 'leave' }[kind];
      });
      d.setBody([h('div', { class: 'caption' }, `${rows.length} ta xodim`), table({ rows, dense: true, onRow: (r) => { d.close(); app.go(`/employees/${r.id}`); }, columns: [
        { key: 'personnel_no', label: 'Tabel №' }, { key: 'name', label: 'F.I.Sh.', render: (r) => `${r.last_name} ${r.first_name}` },
        { key: 'department_name', label: "Bo'lim" }, { key: 'in', label: 'Kirish', render: (r) => fmtTime(r.s.first_in, app.tz) },
        { key: 'late', label: 'Kechikish', num: true, render: (r) => (r.s.late_min ? `${r.s.late_min} daq` : '—') },
        { key: 'st', label: 'Holat', render: (r) => statusBadge(r.s.status) }] })]);
      d.setFooter([btn('Jurnalda ochish', { variant: 'secondary', onClick: () => { d.close(); app.go(`/attendance/events?from=${state.date}`); } })]);
    } catch (e) { d.setBody(errorState(e)); }
  }

  // live feed
  const feed = h('div', { class: 'feed', 'aria-live': 'polite' });
  let paused = false, pending = [];
  const pendingPill = btn('', { variant: 'secondary', size: 's', cls: 'newer-pill', onClick: () => { flush(); } });
  pendingPill.hidden = true;
  const pauseBtn = btn('', { variant: 'tertiary', size: 's', icon: '⏸', title: "Lentani to'xtatish", onClick: () => { paused = !paused; pauseBtn.querySelector('span').textContent = paused ? '▶' : '⏸'; if (!paused) flush(); } });
  feedBox.append(h('h3', {}, 'Real vaqt lentasi', h('span', { class: 'right' }, pauseBtn)), pendingPill, feed);
  function feedItem(e) {
    const bad = ['pad', 'unknown', 'denied'].includes(e.result);
    return h('div', { class: `item ${bad ? 'bad' : ''}`, tabIndex: 0, onclick: () => openEventDrawer(app, e.id), onkeydown: (ev) => ev.key === 'Enter' && openEventDrawer(app, e.id) },
      h('span', { class: 'tabular small' }, fmtTime(e.captured_at, app.tz)), h('span', { class: 'avatar' }, e.name ? initials(e.name) : '?'),
      h('div', { style: { minWidth: 0 } }, h('div', { class: 'small', style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, e.name || "Noma'lum shaxs"),
        h('div', { class: 'caption' }, `${e.direction === 'in' ? '→ kirish' : '← chiqish'} · ${e.access_point || ''}${e.late || e.late_arrival ? ' · ⏱ offline' : ''}`)),
      statusBadge(e.result));
  }
  function flush() { pending.reverse().forEach((e) => feed.prepend(feedItem(e))); pending = []; pendingPill.hidden = true; while (feed.children.length > 50) feed.lastChild.remove(); }
  try {
    const initial = await app.api.get('/api/v1/dashboard/feed');
    if (!initial.items.length) feed.appendChild(emptyState({ icon: '◉', title: "Bugun hali hodisa yo'q" }));
    initial.items.forEach((e) => feed.appendChild(feedItem(e)));
  } catch (e) { feed.appendChild(errorState(e)); }
  const onEvent = (ev) => {
    if (!document.body.contains(feed)) { app.live.removeEventListener('event', onEvent); return; }
    feed.querySelector('.state')?.remove();
    if (paused) { pending.push(ev.detail); pendingPill.hidden = false; pendingPill.querySelector('.lbl').textContent = `${pending.length} ta yangi`; }
    else { feed.prepend(feedItem(ev.detail)); while (feed.children.length > 50) feed.lastChild.remove(); }
    debouncedRefresh();
  };
  const debouncedRefresh = debounce(refresh, 3000);
  app.live.addEventListener('event', onEvent);
  await refresh();
  const timer = setInterval(() => { if (!document.body.contains(kpiBox)) clearInterval(timer); else refresh(); }, 60000);
}

export async function renderLive(main, params, app) {
  main.append(pageHead('Jonli lenta', 'Barcha kirish nuqtalaridagi hodisalar real vaqtda'));
  const box = h('div', { class: 'card' });
  main.appendChild(box);
  const rows = [];
  const tbl = h('div');
  box.appendChild(tbl);
  const draw = () => { clear(tbl).appendChild(table({ rows, onRow: (e) => openEventDrawer(app, e.id), rowClass: (e) => (['pad', 'unknown', 'denied'].includes(e.result) ? 'flag-danger' : ''), columns: [
    { key: 'captured_at', label: 'Vaqt', render: (e) => fmtDateTime(e.captured_at, app.tz) }, { key: 'name', label: 'Xodim', render: (e) => e.name || "Noma'lum" },
    { key: 'direction', label: "Yo'nalish", render: (e) => (e.direction === 'in' ? '→ kirish' : '← chiqish') }, { key: 'access_point', label: 'Darvoza' },
    { key: 'method', label: 'Usul' }, { key: 'result', label: 'Natija', render: (e) => statusBadge(e.result) }] })); };
  try { (await app.api.get('/api/v1/dashboard/feed')).items.forEach((e) => rows.push(e)); } catch (e) { box.appendChild(errorState(e)); }
  draw();
  const on = (ev) => { if (!document.body.contains(tbl)) return app.live.removeEventListener('event', on); rows.unshift(ev.detail); rows.length = Math.min(rows.length, 200); draw(); };
  app.live.addEventListener('event', on);
}

