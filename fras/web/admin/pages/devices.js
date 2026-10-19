// SCR-60 … SCR-65: devices, registration, detail (health, config, diagnostics, queue, logs), groups, firmware.
import { h, clear, btn, select, input, field, form, table, tabs, modal, toast, statusBadge, badge, emptyState, load, kv, confirmDanger, showError, textarea, errorState } from '/assets/core/ui.js';
import { fmtDateTime, relTime } from '/assets/core/format.js';
import { pageHead, orgTree, act } from './common.js';

export async function renderList(main, params, app) {
  const q = app.query();
  const st = { status: q.status || '', type: '' };
  const sumBox = h('div', { class: 'grid cols-6' }), box = h('div');
  const statusSel = select([['', 'Barcha holatlar'], ['online', 'Online'], ['degraded', 'Degraded'], ['offline', 'Offline'], ['pending', 'Aktivatsiya kutmoqda'], ['decommissioned', 'Ishdan chiqarilgan']], { value: st.status });
  const typeSel = select([['', 'Barcha turlar'], ['terminal', 'Terminal'], ['camera', 'Kamera'], ['controller', 'Turniket kontroller'], ['site_server', 'Site server']]);
  statusSel.addEventListener('change', () => { st.status = statusSel.value; refresh(); });
  typeSel.addEventListener('change', () => { st.type = typeSel.value; refresh(); });
  main.append(pageHead('Qurilmalar va turniketlar', null, [app.can('device.manage') ? btn("Qurilma qo'shish", { icon: '+', onClick: () => app.go('/devices/register') }) : null,
    btn('Guruhlar', { variant: 'secondary', onClick: () => app.go('/devices/groups') }), btn('Firmware', { variant: 'secondary', onClick: () => app.go('/devices/firmware') })]),
  sumBox, h('div', { class: 'filters', style: { marginTop: '12px' } }, field({ label: 'Holat', input: statusSel }), field({ label: 'Turi', input: typeSel })), box);
  async function refresh() {
    app.setQuery({ status: st.status });
    await load(box, () => app.api.get('/api/v1/devices', { query: { status: st.status || undefined, type: st.type || undefined } }), (r) => {
      clear(sumBox).append(...[['Online', r.summary.online, ''], ['Degraded', r.summary.degraded, r.summary.degraded ? 'warn' : ''], ['Offline', r.summary.offline, r.summary.offline ? 'danger' : ''], ['Yangilash kutmoqda', r.summary.updates_pending, '']]
        .map(([l, v, c]) => h('div', { class: `kpi ${c}`, style: { minHeight: '84px', cursor: 'default' } }, h('div', { class: 'label' }, l), h('div', { class: 'value' }, v))));
      return table({ rows: r.items, onRow: (d) => app.go(`/devices/${d.id}`), rowClass: (d) => (d.status === 'offline' ? 'flag-danger' : ''),
        empty: emptyState({ icon: '📟', title: "Qurilmalar yo'q", action: app.can('device.manage') ? btn("Qurilma qo'shish", { onClick: () => app.go('/devices/register') }) : null }), columns: [
          { key: 'status', label: 'Holat', render: (d) => statusBadge(d.status) }, { key: 'name', label: 'Nomi' }, { key: 'type', label: 'Turi' },
          { key: 'loc', label: 'Joylashuv', render: (d) => `${d.site_name}${d.access_point_name ? ` → ${d.access_point_name}` : ''}` }, { key: 'direction', label: "Yo'nalish" },
          { key: 'last_seen_at', label: 'Oxirgi aloqa', render: (d) => h('span', { title: fmtDateTime(d.last_seen_at, app.tz) }, d.last_seen_at ? relTime(d.last_seen_at) : '—') },
          { key: 'firmware', label: 'Firmware' }, { key: 'config', label: 'Konfig', render: (d) => (d.config_drift ? badge(`v${d.applied_config_version}→v${d.config_version}`, 'warning', '⚠') : `v${d.config_version}`) },
          { key: 'gallery_version', label: 'Galereya', num: true }, { key: 'outbox_size', label: 'Navbat', num: true }, { key: 'serial', label: 'Seriya №' }] });
    });
  }
  await refresh();
  const onDev = () => { if (!document.body.contains(box)) app.live.removeEventListener('device', onDev); else refresh(); };
  app.live.addEventListener('device', onDev);
}

export async function renderRegister(main, params, app) {
  const tree = await orgTree(app, true);
  const groups = (await app.api.get('/api/v1/device-groups')).items;
  const f = form([{ name: 'name', label: 'Nomi', required: true, minlength: 2, placeholder: 'Masalan: Asosiy darvoza — kirish' },
    { name: 'type', label: 'Turi', type: 'select', options: [['terminal', 'Terminal'], ['camera', 'Kamera'], ['controller', 'Turniket kontroller'], ['site_server', 'Site server']] },
    { name: 'site_id', label: 'Zavod', type: 'select', options: tree.sites.map((s) => [s.id, s.name]), required: true },
    { name: 'access_point_id', label: 'Darvoza (kirish nuqtasi)', type: 'select', options: [['', '—']] },
    { name: 'direction', label: "Yo'nalish", type: 'select', options: [['in', 'Kirish'], ['out', 'Chiqish'], ['both', 'Ikkalasi']] },
    { name: 'group_id', label: 'Guruh (konfig profili)', type: 'select', options: [['', '—'], ...groups.map((g) => [g.id, g.name])] },
    { name: 'serial', label: 'Seriya raqami', maxlength: 64 }]);
  const siteSel = f.fields.site_id.ctl, apSel = f.fields.access_point_id.ctl;
  const fillAps = () => { clear(apSel); apSel.appendChild(h('option', { value: '' }, '—')); (tree.sites.find((s) => s.id === siteSel.value)?.access_points || []).forEach((a) => apSel.appendChild(h('option', { value: a.id }, a.name))); };
  siteSel.addEventListener('change', fillAps); fillAps();
  const result = h('div');
  main.append(pageHead("Qurilmani ro'yxatga olish", '1) Ma\'lumotlar → 2) Bir martalik aktivatsiya kodi → 3) Qurilmada kodni kiritish', [], [['Qurilmalar', '/devices'], ["Qo'shish"]]),
    h('div', { class: 'card pad-lg stack' }, f.el, h('div', { class: 'btn-bar' }, btn('Kod yaratish', { onClick: async () => {
      if (!f.validate()) return;
      const v = f.values(); for (const k of Object.keys(v)) if (v[k] === null) delete v[k];
      try { const r = await app.api.post('/api/v1/devices', v); showCode(r); } catch (e) { if (e.code === 'PLAN_LIMIT') toast(e.message, 'error'); else showError(e, f); }
    } }))), result);
  function showCode(r) {
    clear(result).append(h('div', { class: 'card pad-lg stack', style: { marginTop: '16px' } }, h('h3', {}, 'Aktivatsiya kodi (24 soat amal qiladi)'), h('div', { class: 'qr-box' }, r.activation_code),
      h('div', { class: 'caption' }, 'Qurilmada: ', h('span', { class: 'mono' }, `python -m fras_edge --server ${location.origin} activate --code ${r.activation_code}`)),
      h('div', { class: 'caption' }, 'QR ma\'lumoti: ', h('span', { class: 'mono' }, r.qr_payload)), h('div', { class: 'note', id: 'wait' }, '⏳ Qurilma ulanishini kutish…'),
      h('div', { class: 'btn-bar' }, btn('Qurilma sahifasi', { variant: 'secondary', onClick: () => app.go(`/devices/${r.id}`) }))));
    const t0 = Date.now();
    const poll = setInterval(async () => {
      if (!document.body.contains(result) || Date.now() - t0 > 600000) { clearInterval(poll); return; }
      try { const d = await app.api.get(`/api/v1/devices/${r.id}`); if (d.activated) { clearInterval(poll); const w = result.querySelector('#wait'); w.className = 'note success'; w.textContent = `✓ Qurilma ulandi${d.serial ? `: S/N ${d.serial}` : ''}. Galereya yuklanmoqda.`; } } catch { /* keep waiting */ }
    }, 3000);
  }
}

export async function renderDetail(main, params, app) {
  let d;
  try { d = await app.api.get(`/api/v1/devices/${params.id}`); } catch (e) { main.appendChild(errorState(e)); return; }
  const tabBox = h('div'), body = h('div');
  const cmd = async (type, extra = {}) => {
    const r = await act(() => app.api.post(`/api/v1/devices/${d.id}/commands`, { type, ...extra }));
    if (r) toast(r.note, 'info');
    return r;
  };
  const actions = [];
  if (app.can('device.restart') && d.status !== 'decommissioned') actions.push(btn('Restart', { variant: 'danger-outline', onClick: () => confirmDanger({ title: `Restart: ${d.name}`,
    consequences: ['Bu darvoza ~60 s ishlamaydi', 'Navbatdagi eventlar saqlanadi'], reasonMin: 10, okLabel: 'Restart', onConfirm: async ({ reason }) => { await app.api.post(`/api/v1/devices/${d.id}/commands`, { type: 'restart', reason }); toast('Buyruq yuborildi', 'success'); } }) }));
  if (app.can('device.open_gate') && d.type !== 'camera' && d.status !== 'decommissioned') actions.push(btn('Turniketni ochish', { variant: 'danger-outline', onClick: () => {
    const code = input({ inputmode: 'numeric', maxlength: 6, placeholder: 'MFA kodi (yoqilgan bo\'lsa)' });
    confirmDanger({ title: 'Turniketni masofadan ochish', consequences: ['Bir martalik ochish (5 s)', 'Xavfsizlik xizmatiga ogohlantirish yuboriladi'], reasonMin: 10, extra: field({ label: 'MFA tasdiq', input: code }), okLabel: 'Ochish',
      onConfirm: async ({ reason }) => { await app.api.post(`/api/v1/devices/${d.id}/commands`, { type: 'open_gate', reason, mfa_code: code.value || null }); toast('Ochish buyrug\'i yuborildi', 'success'); } });
  } }));
  if (app.can('device.manage') && !d.activated) actions.push(btn('Yangi aktivatsiya kodi', { variant: 'secondary', onClick: async () => { const r = await act(() => app.api.post(`/api/v1/devices/${d.id}/activation-code`)); if (r) modal({ title: 'Aktivatsiya kodi', body: [h('div', { class: 'qr-box' }, r.activation_code), h('div', { class: 'caption' }, `Amal qiladi: ${fmtDateTime(r.expires_at, app.tz)}`)] }); } }));
  if (app.can('device.manage') && d.status !== 'decommissioned') actions.push(btn('Ishdan chiqarish', { variant: 'danger', onClick: () => confirmDanger({ title: 'Qurilmani ishdan chiqarish',
    consequences: ['Sertifikat bekor qilinadi', 'Qurilmadagi lokal ma\'lumot (galereya, navbat) o\'chiriladi', 'Qaytarib bo\'lmaydi'], confirmWord: d.name, okLabel: 'Ishdan chiqarish',
    onConfirm: async ({ word }) => { const r = await app.api.post(`/api/v1/devices/${d.id}/decommission`, { confirm_name: word }); toast(r.note || 'Qurilma ishdan chiqarildi', 'success'); app.go('/devices'); } }) }));
  main.append(pageHead(d.name, h('span', { class: 'row' }, statusBadge(d.status), `${d.type} · ${d.serial || 'S/N —'}`), actions, [['Qurilmalar', '/devices'], [d.name]]), tabBox, body);
  const TABS = [['health', 'Holat'], ['config', 'Konfiguratsiya'], ['diag', 'Diagnostika'], ['queue', 'Buyruqlar va navbat'], ['history', 'Tarix']];
  const show = (k) => {
    clear(tabBox).appendChild(tabs(TABS.map(([key, label]) => ({ key, label })), k, show)); clear(body);
    const hl = d.health || {};
    if (k === 'health') body.appendChild(h('div', { class: 'grid cols-2' }, h('div', { class: 'card' }, kv([
      ['Oxirgi aloqa', d.last_seen_at ? `${relTime(d.last_seen_at)} (${fmtDateTime(d.last_seen_at, app.tz)})` : '—'], ['Firmware', d.firmware], ['Kamera', hl.camera_ok === false ? badge('Xato', 'danger') : `${hl.camera_fps ?? '—'} FPS`],
      ['Disk', hl.disk_pct !== undefined ? `${hl.disk_pct}%` : '—'], ['Yuklama', hl.load ?? '—'], ['Soat siljishi', d.clock_skew_ms !== null && d.clock_skew_ms !== undefined ? `${(d.clock_skew_ms / 1000).toFixed(1)} s` : '—'],
      ['Navbat (outbox)', `${d.outbox_size} ta (${hl.outbox_fill_pct ?? 0}%)`], ['Oxirgi ACK seq', d.last_acked_seq], ['Galereya versiyasi', d.gallery_version]])),
      h('div', { class: 'card' }, kv([['Bugungi hodisalar', d.events_today], ['Bugun rad etilgan', d.rejected_today], ['Joylashuv', `${d.site_id}`], ["Yo'nalish", d.direction],
        ['Konfig', d.config_drift ? badge(`Qo'llanmagan: v${d.applied_config_version} → v${d.config_version}`, 'warning') : `v${d.config_version}`]]))));
    if (k === 'config') {
      const ta = textarea({ rows: 12, class: 'input mono' });
      ta.value = JSON.stringify(d.config_override, null, 2);
      body.appendChild(h('div', { class: 'grid cols-2' }, h('div', { class: 'card stack' }, h('h3', {}, "Qurilma override (JSON)"), ta,
        app.can('device.manage') ? h('div', { class: 'btn-bar' }, btn('Konfigni qo\'llash', { onClick: async () => {
          let v; try { v = JSON.parse(ta.value || '{}'); } catch { toast('JSON xato', 'error'); return; }
          const r = await act(() => app.api.patch(`/api/v1/devices/${d.id}`, { config_override: v }), 'Konfiguratsiya yuborildi. Qurilma qabul qilgach versiya yangilanadi.');
          if (r) { d = await app.api.get(`/api/v1/devices/${d.id}`); show('config'); }
        } })) : null), h('div', { class: 'card' }, h('h3', {}, 'Amaldagi konfiguratsiya (guruh + override)'), h('pre', { class: 'mono' }, JSON.stringify(d.effective_config, null, 2)))));
    }
    if (k === 'diag') body.appendChild(h('div', { class: 'card stack' }, h('p', { class: 'muted' }, 'Masofaviy testlar. Natija qurilma javob bergach "Buyruqlar" bo\'limida ko\'rinadi.'),
      ...[['camera', 'Kamera kadri testi (shaxssiz ramka)'], ['relay', 'Turniket relay testi'], ['network', 'Tarmoq ping'], ['gallery', 'Galereya butunligi']].map(([t, l]) => h('div', { class: 'row' }, h('span', { style: { flex: 1 } }, l),
        app.can('device.manage') ? btn('Testni boshlash', { variant: 'secondary', size: 's', onClick: () => cmd('diagnostic', { test: t }) }) : null)),
      app.can('device.manage') ? h('div', { class: 'row' }, h('span', { style: { flex: 1 } }, 'Galereyani majburan yangilash'), btn('Sinxronlash', { variant: 'secondary', size: 's', onClick: () => cmd('gallery_sync') })) : null));
    if (k === 'queue') body.appendChild(table({ rows: d.commands, empty: emptyState({ title: "Buyruqlar yo'q" }), columns: [
      { key: 'created_at', label: 'Vaqt', render: (c) => fmtDateTime(c.created_at, app.tz) }, { key: 'type', label: 'Buyruq' }, { key: 'status', label: 'Holat', render: (c) => statusBadge(c.status) },
      { key: 'reason', label: 'Sabab' }, { key: 'created_by_name', label: 'Kim' }, { key: 'result', label: 'Natija', wrap: true, render: (c) => (c.result ? h('span', { class: 'mono' }, JSON.stringify(c.result)) : '—') }] }));
    if (k === 'history') body.appendChild(table({ rows: d.history, columns: [{ key: 'created_at', label: 'Vaqt', render: (a) => fmtDateTime(a.created_at, app.tz) }, { key: 'action', label: 'Amal' }, { key: 'actor_name', label: 'Kim' }] }));
  };
  show('health');
}

export async function renderGroups(main, params, app) {
  const box = h('div');
  main.append(pageHead('Qurilma guruhlari', 'Guruh profili o\'zgarsa barcha qurilmalarga konfiguratsiya yuboriladi', [app.can('device.manage') ? btn('Guruh yaratish', { icon: '+', onClick: () => edit(null) }) : null], [['Qurilmalar', '/devices'], ['Guruhlar']]), box);
  let defaults = {};
  async function refresh() {
    await load(box, () => app.api.get('/api/v1/device-groups'), (r) => { defaults = r.defaults; return table({ rows: r.items, onRow: app.can('device.manage') ? edit : null, empty: emptyState({ title: "Guruhlar yo'q" }), columns: [
      { key: 'name', label: 'Nomi' }, { key: 'devices', label: 'Qurilmalar', num: true }, { key: 'config_version', label: 'Versiya' }, { key: 'config', label: 'Profil', wrap: true, render: (g) => h('span', { class: 'mono' }, JSON.stringify(g.config)) }] }); });
  }
  function edit(g) {
    const name = input({ value: g?.name || '' });
    const ta = textarea({ rows: 10, class: 'input mono' });
    ta.value = JSON.stringify(g?.config || {}, null, 2);
    const m = modal({ title: g ? `Guruh: ${g.name}` : 'Yangi guruh', size: 'w640', body: [field({ label: 'Nomi', input: name }), field({ label: 'Profil (JSON)', input: ta, help: `Kalitlar: ${Object.keys(defaults).join(', ')}` })],
      footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn('Saqlash', { onClick: async () => {
        let cfg; try { cfg = JSON.parse(ta.value || '{}'); } catch { toast('JSON xato', 'error'); return; }
        const r = await act(() => (g ? app.api.put(`/api/v1/device-groups/${g.id}`, { name: name.value, config: cfg }) : app.api.post('/api/v1/device-groups', { name: name.value, config: cfg })), 'Saqlandi');
        if (r) { if (r.devices_updated) toast(`${r.devices_updated} ta qurilmaga yuborildi`, 'info'); m.close(); refresh(); }
      } })] });
  }
  await refresh();
}

export async function renderFirmware(main, params, app) {
  const box = h('div');
  main.append(pageHead('Firmware relizlari', 'Bosqichma-bosqich: 5% → 25% → 100%; xato > 2% bo\'lsa avtomatik pauza', [app.can('device.manage') ? btn("Reliz qo'shish", { icon: '+', onClick: () => addRelease() }) : null], [['Qurilmalar', '/devices'], ['Firmware']]), box);
  let groups = [];
  async function refresh() {
    groups = (await app.api.get('/api/v1/device-groups')).items;
    await load(box, () => app.api.get('/api/v1/firmware'), (r) => [h('h2', {}, 'Relizlar'), table({ rows: r.releases, empty: emptyState({ title: "Relizlar yo'q" }), columns: [
      { key: 'version', label: 'Versiya' }, { key: 'sha256', label: 'SHA-256', render: (x) => h('span', { class: 'mono' }, `${x.sha256.slice(0, 16)}…`) }, { key: 'notes', label: 'Izoh', wrap: true },
      { key: 'act', label: '', render: (x) => (app.can('device.manage') ? btn('Rollout', { variant: 'secondary', size: 's', onClick: () => rollout(x) }) : '') }] }),
    h('h2', { style: { marginTop: '24px' } }, 'Rolloutlar'), table({ rows: r.rollouts, empty: emptyState({ title: "Rolloutlar yo'q" }), columns: [
      { key: 'version', label: 'Versiya' }, { key: 'group_name', label: 'Guruh' }, { key: 'stage_pct', label: 'Bosqich', render: (x) => `${x.stage_pct}%` }, { key: 'progress', label: 'Yangilangan', render: (x) => `${x.updated} / ${x.devices}` },
      { key: 'status', label: 'Holat', render: (x) => statusBadge(x.status) }, { key: 'window', label: 'Oyna', render: (x) => `${x.window_from}–${x.window_to}` },
      { key: 'act', label: '', render: (x) => (app.can('device.manage') ? h('span', { class: 'row' }, ...(x.status === 'running' ? [btn('Keyingi bosqich', { variant: 'secondary', size: 's', onClick: () => doAction(x, 'advance') }), btn('Pauza', { variant: 'tertiary', size: 's', onClick: () => doAction(x, 'pause') })] : x.status === 'paused' ? [btn('Davom', { variant: 'secondary', size: 's', onClick: () => doAction(x, 'resume') }), btn('Rollback', { variant: 'danger-outline', size: 's', onClick: () => doAction(x, 'rollback') })] : [])) : '') }] })]);
  }
  async function doAction(x, action) { try { await app.api.post(`/api/v1/firmware/rollouts/${x.id}/${action}`); toast('Bajarildi', 'success'); } catch (e) { showError(e); } refresh(); }
  function addRelease() {
    const f = form([{ name: 'version', label: 'Versiya', required: true, regex: '^\\d+\\.\\d+\\.\\d+$', regexMessage: 'X.Y.Z' }, { name: 'sha256', label: 'SHA-256', required: true, regex: '^[0-9a-f]{64}$', regexMessage: '64 ta hex belgi' }, { name: 'notes', label: 'Izoh', type: 'textarea', full: true }]);
    const m = modal({ title: "Reliz qo'shish", body: f.el, footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn('Saqlash', { onClick: async () => { if (!f.validate()) return; if (await act(() => app.api.post('/api/v1/firmware', f.values()), 'Saqlandi', f)) { m.close(); refresh(); } } })] });
  }
  function rollout(rel) {
    const g = select(groups.map((x) => [x.id, x.name]));
    const from = input({ type: 'time', value: '23:00' }), to = input({ type: 'time', value: '05:00' });
    const m = modal({ title: `Rollout ${rel.version}`, body: [field({ label: 'Guruh', input: g }), h('div', { class: 'form-grid' }, field({ label: 'Oyna dan', input: from }), field({ label: 'gacha', input: to })), h('div', { class: 'note' }, 'Smenalar orasidagi vaqtni tanlang. Birinchi bosqich: 5% qurilma.')],
      footer: [btn('Bekor qilish', { variant: 'tertiary', onClick: () => m.close() }), btn('Boshlash', { onClick: async () => { if (await act(() => app.api.post('/api/v1/firmware/rollouts', { release_id: rel.id, group_id: g.value, window_from: from.value, window_to: to.value }), 'Rollout boshlandi')) { m.close(); refresh(); } } })] });
  }
  await refresh();
}
