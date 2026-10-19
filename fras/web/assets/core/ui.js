// DOM helpers and components (spec F.4). No framework: small functions returning elements.
import { t } from './i18n.js';

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k === 'html') el.innerHTML = v;
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  append(el, children);
  return el;
}
export function append(el, children) {
  for (const c of [].concat(children)) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
export const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };
export const $ = (sel, root = document) => root.querySelector(sel);

// ---------------------------------------------------------------- buttons
export function btn(label, { variant = 'primary', size = '', onClick, icon, id, disabled, title, type = 'button', cls = '' } = {}) {
  const b = h('button', { class: `btn ${variant === 'primary' ? '' : variant} ${size} ${cls}`.trim(), type, id, title, 'aria-label': title || undefined },
    icon ? h('span', { 'aria-hidden': 'true' }, icon) : null, label ? h('span', { class: 'lbl' }, label) : null);
  if (disabled) { b.setAttribute('aria-disabled', 'true'); if (typeof disabled === 'string') b.title = disabled; }
  if (onClick) {
    b.addEventListener('click', async (e) => {
      if (b.getAttribute('aria-disabled') === 'true' || b.dataset.loading) return;
      const res = onClick(e);
      if (res && typeof res.then === 'function') {
        b.setLoading(true);
        try { await res; } finally { b.setLoading(false); }
      }
    });
  }
  b.setLoading = (on) => {
    if (on) {
      b.dataset.loading = '1'; b.style.minWidth = `${b.offsetWidth}px`; b.setAttribute('aria-busy', 'true');
      b.prepend(h('span', { class: 'spin', 'aria-hidden': 'true' }));
    } else { delete b.dataset.loading; b.removeAttribute('aria-busy'); b.querySelector('.spin')?.remove(); }
  };
  return b;
}

// ---------------------------------------------------------------- badges
const STATUS = {
  present: ['Keldi', 'success', '✓'], late: ['Kechikdi', 'warning', '⏱'], absent: ['Kelmadi', 'danger', '✕'],
  leave: ["Ta'tilda", 'info', '✈'], off: ['Dam olish', '', '·'], holiday: ['Bayram', '', '★'],
  incomplete: ['Anomaliya', 'purple', '?'], scheduled: ['Rejada', '', '…'], business_trip: ['Xizmat safari', 'info', '✈'],
  remote: ['Masofaviy', 'info', '⌂'],
  accepted: ['Qabul', 'success', '✓'], review: ['Tekshiruvda', 'warning', '⚠'], unknown: ["Noma'lum", 'danger', '?'],
  pad: ['Soxta tasvir', 'danger', '⛔'], denied: ['Ruxsat yo\'q', 'danger', '✕'], duplicate: ['Takroriy', 'info', '↻'],
  verified: ['Tasdiqlandi', 'success', '✓'], rejected: ['Rad etildi', 'danger', '✕'], pending: ['Kutilmoqda', 'warning', '…'],
  approved: ['Tasdiqlandi', 'success', '✓'], cancelled: ['Bekor', '', '✕'],
  online: ['Online', 'success', '●'], offline: ['Offline', 'danger', '●'], degraded: ['Degraded', 'warning', '●'],
  decommissioned: ['Ishdan chiqarilgan', '', '■'], active: ['Faol', 'success', '✓'], deactivated: ['Deaktiv', '', '■'],
  none: ["Yo'q", '', '—'], revoked: ['Bekor qilingan', '', '✕'], declined: ['Rad etgan', 'info', '✕'],
  invited: ['Taklif yuborilgan', 'info', '✉'], blocked: ['Bloklangan', 'danger', '■'],
  open: ['Ochiq', 'warning', '●'], closed: ['Yopilgan', '', '🔒'], resolved: ['Hal qilingan', 'success', '✓'],
  new: ['Yangi', 'danger', '●'], in_review: ["Ko'rib chiqilmoqda", 'warning', '●'], reopen_requested: ['Qayta ochish so\'ralgan', 'warning', '…'],
  ready: ['Tayyor', 'success', '✓'], running: ['Tayyorlanmoqda', 'info', '…'], failed: ['Xato', 'danger', '✕'], expired: ['Muddati o\'tgan', '', '⌛'],
  trialing: ['Sinov', 'info', '…'], past_due: ["To'lov kechikdi", 'warning', '!'], restricted: ['Cheklangan', 'warning', '!'],
  suspended: ["To'xtatilgan", 'danger', '!'], archived: ['Arxiv', '', '■'], issued: ['Chiqarilgan', 'info', '•'],
  paid: ["To'langan", 'success', '✓'], overdue: ["Muddati o'tgan", 'danger', '!'], void: ['Bekor', '', '✕'],
  queued: ['Navbatda', '', '…'], sent: ['Yuborildi', 'info', '→'], acked: ['Bajarildi', 'success', '✓'],
  low: ['Past', '', '•'], medium: ["O'rta", 'warning', '•'], high: ['Yuqori', 'danger', '•'], critical: ['Kritik', 'danger', '‼'],
};
export function badge(text, kind = '', icon = '') {
  return h('span', { class: `badge ${kind}` }, icon ? h('span', { 'aria-hidden': 'true' }, icon) : null, text);
}
export function statusBadge(status) {
  const [label, kind, icon] = STATUS[status] || [status ?? '—', '', ''];
  return badge(label, kind, icon);
}
export const statusLabel = (s) => (STATUS[s] || [s])[0];

// ---------------------------------------------------------------- form fields
export function field({ label, required, help, input, error, full, id }) {
  const fid = id || input?.id || `f${Math.random().toString(36).slice(2, 8)}`;
  if (input && !input.id) input.id = fid;
  const errEl = h('div', { class: 'err', role: 'alert' }, error || '');
  if (!error) errEl.hidden = true;
  const wrap = h('div', { class: `field ${full ? 'full' : ''}` },
    label ? h('label', { for: fid }, label, required ? h('span', { class: 'req', 'aria-hidden': 'true' }, '*') : null) : null,
    input, help ? h('div', { class: 'help' }, help) : null, errEl);
  wrap.setError = (msg) => { errEl.textContent = msg || ''; errEl.hidden = !msg; wrap.classList.toggle('invalid', !!msg); if (input) input.setAttribute('aria-invalid', msg ? 'true' : 'false'); };
  if (error) wrap.setError(error);
  return wrap;
}
export function input(attrs = {}) { return h('input', { class: 'input', type: 'text', ...attrs }); }
export function textarea(attrs = {}) { return h('textarea', { class: 'input', ...attrs }); }
export function select(options, attrs = {}) {
  const s = h('select', { class: 'input', ...attrs });
  for (const o of options) {
    const [value, label] = Array.isArray(o) ? o : [o.value, o.label];
    s.appendChild(h('option', { value }, label));
  }
  if (attrs.value !== undefined) s.value = attrs.value;
  return s;
}
export function checkbox(label, attrs = {}) {
  const i = h('input', { type: 'checkbox', ...attrs });
  const l = h('label', { class: 'check' }, i, label);
  l.input = i; return l;
}

// Simple form controller: named fields, client validation, server 422 mapping.
export function form(defs, values = {}) {
  const fields = {};
  const nodes = [];
  for (const d of defs) {
    let el;
    if (d.type === 'select') el = select(d.options, { name: d.name });
    else if (d.type === 'textarea') el = textarea({ name: d.name, rows: d.rows || 3, maxlength: d.maxlength });
    else if (d.type === 'checkbox') el = checkbox(d.label, { name: d.name });
    else el = input({ name: d.name, type: d.type || 'text', placeholder: d.placeholder, min: d.min, max: d.max, step: d.step, maxlength: d.maxlength, pattern: d.pattern, autocomplete: d.autocomplete || 'off', inputmode: d.inputmode });
    const ctl = d.type === 'checkbox' ? el.input : el;
    const v = values[d.name] ?? d.value;
    if (v !== undefined && v !== null) { if (d.type === 'checkbox') ctl.checked = !!v; else ctl.value = v; }
    if (d.readonly) ctl.setAttribute('readonly', '');
    const f = d.type === 'checkbox' ? h('div', { class: `field ${d.full ? 'full' : ''}` }, el) : field({ label: d.label, required: d.required, help: d.help, input: el, full: d.full });
    if (!f.setError) f.setError = () => {};
    fields[d.name] = { def: d, ctl, wrap: f };
    if (!d.hidden) nodes.push(f);
    ctl.addEventListener('blur', () => validateOne(fields[d.name]));
  }
  function validateOne(fd) {
    const { def, ctl, wrap } = fd;
    let msg = '';
    const val = def.type === 'checkbox' ? ctl.checked : ctl.value.trim();
    if (def.required && (def.type === 'checkbox' ? !val : !val)) msg = 'Majburiy maydon';
    else if (val && def.minlength && String(val).length < def.minlength) msg = `Kamida ${def.minlength} belgi`;
    else if (val && def.regex && !new RegExp(def.regex).test(val)) msg = def.regexMessage || "Noto'g'ri format";
    else if (def.validate) msg = def.validate(val, api) || '';
    wrap.setError(msg);
    return !msg;
  }
  const api = {
    el: h('div', { class: 'form-grid' }, nodes),
    fields,
    values() {
      const out = {};
      for (const [name, { def, ctl }] of Object.entries(fields)) {
        let v = def.type === 'checkbox' ? ctl.checked : ctl.value.trim();
        if (def.type === 'number' && v !== '') v = Number(v);
        if (v === '' && !def.keepEmpty) v = null;
        out[name] = v;
      }
      return out;
    },
    validate() { let ok = true; let first = null; for (const fd of Object.values(fields)) { if (!validateOne(fd)) { ok = false; first ||= fd.ctl; } } first?.focus(); return ok; },
    serverErrors(err) {
      const fe = err?.fieldErrors || {};
      let any = false;
      for (const [k, msg] of Object.entries(fe)) { if (fields[k]) { fields[k].wrap.setError(msg); any = true; } }
      return any;
    },
    set(name, v) { const f = fields[name]; if (!f) return; if (f.def.type === 'checkbox') f.ctl.checked = !!v; else f.ctl.value = v ?? ''; },
  };
  return api;
}

// ---------------------------------------------------------------- table
export function table({ columns, rows, onRow, selectable = false, selected = new Set(), onSelect, sort, onSort, dense = false, empty, rowClass }) {
  const thead = h('thead', {}, h('tr', {},
    selectable ? h('th', { style: { width: '36px' } }, (() => {
      const all = h('input', { type: 'checkbox', 'aria-label': 'Hammasini tanlash' });
      all.checked = rows.length > 0 && rows.every((r) => selected.has(r.id));
      all.addEventListener('change', () => { rows.forEach((r) => (all.checked ? selected.add(r.id) : selected.delete(r.id))); onSelect?.(selected); });
      return all;
    })()) : null,
    columns.map((c) => {
      const th = h('th', { class: `${c.sort ? 'sortable' : ''} ${c.num ? 'num' : ''}`, scope: 'col', style: c.width ? { width: c.width } : null }, c.label);
      if (c.sort && sort?.key === c.key) th.setAttribute('aria-sort', sort.dir === 'desc' ? 'descending' : 'ascending');
      if (c.sort && onSort) {
        th.tabIndex = 0;
        const go = () => onSort({ key: c.key, dir: sort?.key === c.key && sort.dir === 'asc' ? 'desc' : 'asc' });
        th.addEventListener('click', go); th.addEventListener('keydown', (e) => e.key === 'Enter' && go());
      }
      return th;
    })));
  const tbody = h('tbody');
  rows.forEach((r) => {
    const tr = h('tr', { class: `${onRow ? 'clickable' : ''} ${selected.has(r.id) ? 'selected' : ''} ${rowClass ? rowClass(r) : ''}`, tabIndex: onRow ? 0 : undefined });
    if (selectable) {
      const cb = h('input', { type: 'checkbox', 'aria-label': 'Tanlash' });
      cb.checked = selected.has(r.id);
      cb.addEventListener('click', (e) => e.stopPropagation());
      cb.addEventListener('change', () => { cb.checked ? selected.add(r.id) : selected.delete(r.id); tr.classList.toggle('selected', cb.checked); onSelect?.(selected); });
      tr.appendChild(h('td', {}, cb));
    }
    columns.forEach((c, i) => {
      const v = c.render ? c.render(r) : r[c.key];
      tr.appendChild(h('td', { class: `${c.num ? 'num' : ''} ${c.wrap ? 'wrap' : ''} ${i === 0 && !selectable ? 'sticky-col' : ''}` }, v ?? '—'));
    });
    if (onRow) {
      tr.addEventListener('click', () => onRow(r));
      tr.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') onRow(r);
        if (e.key === 'ArrowDown') tr.nextElementSibling?.focus();
        if (e.key === 'ArrowUp') tr.previousElementSibling?.focus();
      });
    }
    tbody.appendChild(tr);
  });
  const t = h('table', { class: `data ${dense ? 'dense' : ''}` }, thead, tbody);
  const wrap = h('div', { class: 'table-wrap' }, t);
  if (!rows.length) wrap.appendChild(empty || emptyState({ title: "Ma'lumot topilmadi" }));
  return wrap;
}

export function pagination({ total, limit, offset, onChange, sizes = [25, 50, 100] }) {
  const from = total ? offset + 1 : 0, to = Math.min(total, offset + limit);
  const sizeSel = select(sizes.map((s) => [s, `${s} / sahifa`]), { value: limit, 'aria-label': 'Sahifa hajmi', style: { width: '130px', height: '32px' } });
  sizeSel.addEventListener('change', () => onChange({ limit: Number(sizeSel.value), offset: 0 }));
  return h('div', { class: 'pagination' },
    h('span', { class: 'tabular' }, `${from}–${to} / ${total.toLocaleString('ru-RU')}`), sizeSel,
    btn('', { variant: 'secondary', size: 's', icon: '‹', title: 'Oldingi', disabled: offset === 0, onClick: () => onChange({ limit, offset: Math.max(0, offset - limit) }) }),
    btn('', { variant: 'secondary', size: 's', icon: '›', title: 'Keyingi', disabled: to >= total, onClick: () => onChange({ limit, offset: offset + limit }) }));
}

// ---------------------------------------------------------------- tabs
export function tabs(items, active, onChange) {
  return h('div', { class: 'tabs', role: 'tablist' }, items.map((it) => h('button', {
    role: 'tab', class: it.key === active ? 'active' : '', 'aria-selected': it.key === active ? 'true' : 'false',
    onclick: () => onChange(it.key),
  }, it.label, it.count !== undefined ? h('span', { class: 'n' }, it.count) : null)));
}

// ---------------------------------------------------------------- overlays
let openStack = [];
function trapFocus(container) {
  const focusables = () => [...container.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')].filter((x) => !x.disabled && x.offsetParent !== null);
  container.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const f = focusables(); if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  });
  setTimeout(() => (container.querySelector('[autofocus]') || focusables()[0])?.focus(), 30);
}
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && openStack.length) openStack[openStack.length - 1].requestClose(); });

export function modal({ title, body, footer = [], size = '', onClose, dirty }) {
  const prev = document.activeElement;
  const box = h('div', { class: `modal ${size}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
    h('header', {}, h('h2', {}, title), btn('', { variant: 'icon', icon: '✕', title: t('Yopish'), onClick: () => api.requestClose() })),
    h('div', { class: 'body' }, body), footer.length ? h('footer', {}, footer) : null);
  const overlay = h('div', { class: 'overlay', onmousedown: (e) => { if (e.target === overlay) api.requestClose(); } }, box);
  const api = {
    el: box,
    close() { overlay.remove(); openStack = openStack.filter((x) => x !== api); prev?.focus?.(); onClose?.(); },
    requestClose() { if (dirty && dirty() && !window.confirm("Saqlanmagan o'zgarishlar bor. Chiqasizmi?")) return; api.close(); },
    setFooter(nodes) { const f = box.querySelector('footer') || box.appendChild(h('footer')); clear(f); append(f, nodes); },
  };
  document.body.appendChild(overlay); openStack.push(api); trapFocus(box);
  return api;
}

export function drawer({ title, body, footer = [], size = '', onClose, dirty }) {
  const prev = document.activeElement;
  const shade = h('div', { class: 'drawer-overlay', onclick: () => api.requestClose() });
  const box = h('aside', { class: `drawer ${size}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
    h('header', {}, h('h2', {}, title), btn('', { variant: 'icon', icon: '✕', title: t('Yopish'), onClick: () => api.requestClose() })),
    h('div', { class: 'body' }, body), h('footer', {}, footer));
  const api = {
    el: box, body: box.querySelector('.body'),
    close() { shade.remove(); box.remove(); openStack = openStack.filter((x) => x !== api); prev?.focus?.(); onClose?.(); },
    requestClose() { if (dirty && dirty() && !window.confirm("Saqlanmagan o'zgarishlar bor. Chiqasizmi?")) return; api.close(); },
    setBody(nodes) { clear(api.body); append(api.body, nodes); },
    setFooter(nodes) { const f = box.querySelector('footer'); clear(f); append(f, nodes); },
  };
  document.body.append(shade, box); openStack.push(api); trapFocus(box);
  return api;
}

// Dangerous action: consequences list + reason (min chars) + optional typed confirmation word (spec F.5).
export function confirmDanger({ title, consequences = [], reasonMin = 0, reasonLabel = 'Sabab', confirmWord, okLabel = 'Tasdiqlash', extra, onConfirm }) {
  return new Promise((resolve) => {
    const reason = textarea({ rows: 3, placeholder: reasonMin ? `Kamida ${reasonMin} belgi` : '' });
    const word = confirmWord ? input({ placeholder: confirmWord, autocomplete: 'off' }) : null;
    const reasonField = reasonMin ? field({ label: reasonLabel, required: true, input: reason }) : null;
    const wordField = word ? field({ label: `Tasdiqlash uchun "${confirmWord}" deb yozing`, required: true, input: word }) : null;
    const errBox = h('div', { class: 'note danger', hidden: true });
    const ok = btn(okLabel, {
      variant: 'danger', onClick: async () => {
        if (reasonMin && reason.value.trim().length < reasonMin) { reasonField.setError(`Kamida ${reasonMin} belgi`); return; }
        if (word && word.value.trim().toUpperCase() !== confirmWord.toUpperCase()) { wordField.setError('Mos kelmadi'); return; }
        try { const r = await onConfirm({ reason: reason.value.trim(), word: word?.value.trim() }); m.close(); resolve(r ?? true); }
        catch (e) { errBox.hidden = false; errBox.textContent = errorText(e); }
      },
    });
    const m = modal({
      title, onClose: () => resolve(false),
      body: [consequences.length ? h('div', { class: 'consequences' }, h('strong', {}, 'Oqibatlar:'), h('ul', {}, consequences.map((c) => h('li', {}, c)))) : null,
        extra || null, reasonField, wordField, errBox],
      footer: [btn(t('Bekor qilish'), { variant: 'tertiary', onClick: () => m.close() }), ok],
    });
  });
}

// ---------------------------------------------------------------- toast
const toastBox = () => document.querySelector('.toasts') || document.body.appendChild(h('div', { class: 'toasts', 'aria-live': 'polite' }));
export function toast(message, kind = 'info', { undo, timeout } = {}) {
  const ms = timeout ?? { success: 4000, info: 6000, warning: 8000, error: 0 }[kind];
  const el = h('div', { class: `toast ${kind}`, role: kind === 'error' ? 'alert' : 'status' },
    h('div', { class: 'msg' }, message),
    undo ? btn('Bekor qilish', { variant: 'tertiary', size: 's', onClick: () => { undo(); el.remove(); } }) : null,
    h('button', { 'aria-label': t('Yopish'), onclick: () => el.remove() }, '✕'));
  const box = toastBox();
  box.appendChild(el);
  while (box.children.length > 3) box.firstChild.remove();
  if (ms) setTimeout(() => el.remove(), ms);
  return el;
}
export function errorText(e) {
  if (!e) return 'Xato';
  const map = {
    'ERR-NET': "Server bilan aloqa yo'q. Internet ulanishini tekshiring.", FORBIDDEN: "Bu amal uchun ruxsatingiz yo'q",
    VERSION_CONFLICT: "Ma'lumot boshqa foydalanuvchi tomonidan o'zgartirildi. Yangilang.", RATE_LIMITED: e.message,
    MFA_SETUP_REQUIRED: "Rolingiz uchun ikki bosqichli autentifikatsiya (MFA) yoqilishi shart.",
  };
  const base = map[e.code] || e.message || 'Xato';
  return e.status >= 500 ? `Server xatosi. So'rov ID: ${e.requestId || '—'}` : base;
}
export function showError(e, f) { if (f && f.serverErrors(e)) { toast("Maydonlardagi xatolarni tuzating", 'warning'); return; } toast(errorText(e), 'error'); }

// ---------------------------------------------------------------- popover / menu
export function popover(anchor, content, { onClose } = {}) {
  document.querySelectorAll('.popover').forEach((p) => p.remove());
  const r = anchor.getBoundingClientRect();
  const p = h('div', { class: 'popover', role: 'dialog' }, content);
  document.body.appendChild(p);
  const left = Math.min(window.scrollX + r.left, window.scrollX + window.innerWidth - p.offsetWidth - 8);
  p.style.left = `${Math.max(8, left)}px`; p.style.top = `${window.scrollY + r.bottom + 6}px`;
  const close = (e) => { if (!e || (!p.contains(e.target) && e.target !== anchor)) { p.remove(); document.removeEventListener('mousedown', close); onClose?.(); } };
  setTimeout(() => document.addEventListener('mousedown', close), 0);
  p.close = () => close();
  return p;
}
export function menu(anchor, items) {
  const p = popover(anchor, h('div', { class: 'menu', role: 'menu' }, items.filter(Boolean).map((it) => h('button', {
    role: 'menuitem', class: it.danger ? 'danger' : '', onclick: () => { p.close(); it.onClick(); },
  }, it.label))));
  p.querySelector('button')?.focus();
  return p;
}

// ---------------------------------------------------------------- states
export function skeletonRows(n = 10, cols = 5) {
  return h('div', { class: 'card stack', 'aria-busy': 'true', 'aria-label': t('Yuklanmoqda…') },
    Array.from({ length: n }, () => h('div', { class: 'row' }, Array.from({ length: cols }, (_, i) => h('div', { class: 'skeleton', style: { flex: i === 1 ? 2 : 1 } })))));
}
export function emptyState({ icon = '∅', title = "Ma'lumot topilmadi", text, action } = {}) {
  return h('div', { class: 'state' }, h('div', { class: 'ico', 'aria-hidden': 'true' }, icon), h('h3', {}, title), text ? h('div', {}, text) : null, action || null);
}
export function errorState(e, retry) {
  return h('div', { class: 'state', role: 'alert' }, h('div', { class: 'ico' }, '⚠'), h('h3', {}, errorText(e)),
    h('div', { class: 'code' }, `${e?.code || 'ERR'}${e?.requestId ? ` · ${e.requestId}` : ''}`),
    retry ? btn(t('Qayta urinish'), { variant: 'secondary', onClick: retry }) : null);
}

// Load data into a container with skeleton → content | empty | error states.
export async function load(container, fetcher, render, { skeleton } = {}) {
  clear(container);
  let shown = false;
  const timer = setTimeout(() => { if (!shown) container.appendChild(skeleton || skeletonRows()); }, 300);
  try {
    const data = await fetcher();
    shown = true; clearTimeout(timer); clear(container);
    append(container, render(data));
    return data;
  } catch (e) {
    shown = true; clearTimeout(timer); clear(container);
    container.appendChild(errorState(e, () => load(container, fetcher, render, { skeleton })));
    return null;
  }
}

export function kv(pairs) { return h('dl', { class: 'kv' }, pairs.filter(Boolean).flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v ?? '—')])); }
export function debounce(fn, ms = 300) { let id; return (...a) => { clearTimeout(id); id = setTimeout(() => fn(...a), ms); }; }
