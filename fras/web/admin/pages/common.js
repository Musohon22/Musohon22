// Shared page helpers for the admin SPA.
import { h, input, debounce, clear, toast, errorText, showError } from '/assets/core/ui.js';

export function pageHead(title, sub, actions = [], crumbs = null) {
  return h('div', {},
    crumbs ? h('nav', { class: 'crumbs', 'aria-label': 'Breadcrumb' }, crumbs.flatMap(([label, href], i) => [i ? h('span', { 'aria-hidden': 'true' }, '/') : null,
      href ? h('a', { href: `/app${href}`, 'data-link': '' }, label) : h('span', {}, label)])) : null,
    h('div', { class: 'page-head' }, h('div', { class: 'title' }, h('h1', {}, title), sub ? h('div', { class: 'caption' }, sub) : null),
      h('div', { class: 'actions' }, actions.filter(Boolean))));
}

let orgCache = null;
export async function orgTree(app, force = false) {
  if (!orgCache || force) orgCache = await app.api.get('/api/v1/org/tree');
  return orgCache;
}
export function invalidateOrg() { orgCache = null; }
export async function departments(app) { return (await orgTree(app)).sites.flatMap((s) => s.departments.map((d) => ({ ...d, site_name: s.name }))); }

// Employee search combobox (typeahead, keyboard ↑↓ Enter Esc).
export function employeePicker(app, { onPick, placeholder = 'Xodim: F.I.Sh. yoki tabel №', value } = {}) {
  const inp = input({ placeholder, role: 'combobox', 'aria-autocomplete': 'list', 'aria-expanded': 'false', autocomplete: 'off' });
  const list = h('div', { class: 'popover menu', role: 'listbox', style: { position: 'absolute', display: 'none', zIndex: 80 } });
  const wrap = h('div', { style: { position: 'relative' } }, inp, list);
  let items = [], idx = -1;
  wrap.value = value || null;
  if (value?.label) inp.value = value.label;
  const close = () => { list.style.display = 'none'; inp.setAttribute('aria-expanded', 'false'); };
  const pick = (e) => { wrap.value = e; inp.value = `${e.last_name} ${e.first_name} · ${e.personnel_no}`; close(); onPick?.(e); };
  const search = debounce(async () => {
    const q = inp.value.trim();
    if (q.length < 2) { close(); return; }
    try {
      items = (await app.api.get('/api/v1/employees', { query: { q, limit: 8, tab: 'all' } })).items;
      clear(list); idx = -1;
      items.forEach((e, i) => list.appendChild(h('button', { role: 'option', type: 'button', onclick: () => pick(e), dataset: { i } },
        `${e.last_name} ${e.first_name}`, h('span', { class: 'caption' }, ` · ${e.personnel_no} · ${e.department_name || ''}`))));
      if (!items.length) list.appendChild(h('div', { class: 'caption', style: { padding: '8px' } }, 'Topilmadi'));
      list.style.display = 'block'; list.style.top = `${inp.offsetHeight + 4}px`; list.style.left = '0'; list.style.width = `${Math.max(inp.offsetWidth, 280)}px`;
      inp.setAttribute('aria-expanded', 'true');
    } catch { close(); }
  }, 300);
  inp.addEventListener('input', () => { wrap.value = null; search(); });
  inp.addEventListener('keydown', (e) => {
    const opts = [...list.querySelectorAll('[role=option]')];
    if (e.key === 'ArrowDown') { idx = Math.min(opts.length - 1, idx + 1); opts[idx]?.focus(); e.preventDefault(); }
    if (e.key === 'Escape') close();
  });
  list.addEventListener('keydown', (e) => {
    const opts = [...list.querySelectorAll('[role=option]')];
    if (e.key === 'ArrowDown') { idx = Math.min(opts.length - 1, idx + 1); opts[idx]?.focus(); e.preventDefault(); }
    if (e.key === 'ArrowUp') { idx = Math.max(0, idx - 1); opts[idx]?.focus(); e.preventDefault(); }
    if (e.key === 'Escape') { close(); inp.focus(); }
  });
  inp.addEventListener('blur', () => setTimeout(() => { if (!list.contains(document.activeElement)) close(); }, 150));
  wrap.input = inp;
  return wrap;
}

// Run an API mutation with toast feedback; returns result or null.
export async function act(fn, successMsg, f) {
  try { const r = await fn(); if (successMsg) toast(successMsg, 'success'); return r ?? true; }
  catch (e) { showError(e, f); return null; }
}

export const REASONS = [['missed_checkout', 'Chiqish qayd etilmagan'], ['card_forgotten', 'Karta unutilgan'], ['device_failure', 'Qurilma nosozligi'], ['business_task', 'Xizmat topshirig\'i'], ['other', 'Boshqa']];
export const LEAVE_TYPES = [['vacation', "Mehnat ta'tili"], ['sick', 'Kasallik varaqasi'], ['business_trip', 'Xizmat safari'], ['unpaid', "O'z hisobidan"], ['permission', 'Soatbay ruxsat']];
export { errorText };
