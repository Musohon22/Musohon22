// Public ROI calculator (business tab, section 5). Every number the visitor did not enter is either
// excluded or shown as a labelled assumption — the result is an estimate, not a promise.
import { createApi } from '/assets/core/api.js';
import { h, clear, btn, field, input, toast, errorText, form, kv } from '/assets/core/ui.js';

const api = createApi({ realm: 'public' });
const root = document.getElementById('root');
const usd = (v) => (v === null || v === undefined ? '—' : `${v < 0 ? '−' : ''}$${Math.abs(Number(v)).toLocaleString('en-US', { maximumFractionDigits: 0 })}`);

const f = form([
  { name: 'employees', label: 'Xodimlar soni', type: 'number', required: true, min: 10, help: 'Davomat yuritiladigan faol xodimlar' },
  { name: 'payroll_monthly', label: "Oylik ish haqi fondi ($)", type: 'number', required: true, min: 1 },
  { name: 'hr_hour_cost', label: 'HR xodimining 1 soatlik narxi ($)', type: 'number', step: '0.1', required: true },
  { name: 'hr_hours_now', label: 'Tabel tayyorlashga HR vaqti (soat/oy)', type: 'number', required: true },
  { name: 'fix_hours_now', label: "Tuzatish va nizolarga vaqt (soat/oy)", type: 'number', required: true },
  { name: 'leakage_pct_now', label: "Ortiqcha to'lov ulushi, % (ixtiyoriy)", type: 'number', step: '0.01', help: "Bilmasangiz bo'sh qoldiring — natijaga kirmaydi" },
  { name: 'subscription_monthly', label: 'Obuna narxi ($/oy)', type: 'number', required: true, help: 'Tarif sahifasidan yoki taklifdan' },
  { name: 'devices_cost', label: 'Terminallar ($, bir martalik)', type: 'number', required: true },
  { name: 'install_cost', label: "O'rnatish ($, bir martalik)", type: 'number', required: true },
  { name: 'integration_cost', label: 'Integratsiya ($, ixtiyoriy)', type: 'number' },
], { integration_cost: 0 });

const result = h('div', { class: 'stack' }, h('div', { class: 'note' }, "Qiymatlarni kiriting va \"Hisoblash\" ni bosing."));
let last = null;

function values() {
  const v = f.values();
  for (const k of Object.keys(v)) if (v[k] === null) delete v[k];
  return v;
}

async function calc() {
  if (!f.validate()) return;
  try { last = await api.post('/api/v1/public/roi/calculate', values(), { idempotent: false }); renderResult(last); }
  catch (e) { if (!f.serverErrors(e)) toast(errorText(e), 'error'); }
}

function renderResult(r) {
  const verdict = { pays_back: ['success', `Taxminiy qoplanish: ${r.payback_months} oy`], weak: ['warning', `Qoplanish uzoq: ${r.payback_months} oy`], does_not_pay_back: ['danger', "Kiritilgan qiymatlar bilan tizim o'zini qoplamaydi"] }[r.verdict];
  clear(result).append(
    h('div', { class: `note ${verdict[0]}` }, h('strong', {}, verdict[1])),
    h('div', { class: 'card' }, kv([['Hozirgi xarajat / oy', usd(r.cost_now_monthly)], ['Tizimdan keyin / oy (obuna bilan)', usd(r.cost_after_monthly)],
      ['Oylik sof tejam', usd(r.net_saving_monthly)], ['Yillik sof tejam', usd(r.net_saving_yearly)], ['Bir martalik investitsiya', usd(r.one_time_investment)],
      ['Birinchi yil natijasi', usd(r.first_year_result)]])),
    r.assumptions.length ? h('div', { class: 'card stack' }, h('h3', {}, 'Taxminlar'), h('div', { class: 'caption' }, "Siz kiritmagan \"keyin\" qiymatlari o'rniga ishlatildi:"), r.assumptions.map((a) => h('div', { class: 'small' }, `• ${a.text}`))) : null,
    r.excluded.length ? h('div', { class: 'card stack' }, h('h3', {}, 'Hisobga olinmadi'), r.excluded.map((x) => h('div', { class: 'small' }, `• ${x}`))) : null,
    h('div', { class: 'card' }, h('h3', {}, "Sezgirlik: ortiqcha to'lov ulushi bo'yicha"), h('table', { class: 'data dense' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Ulush'), h('th', { class: 'num' }, 'Oylik tejam'), h('th', { class: 'num' }, 'Qoplanish'))),
      h('tbody', {}, r.sensitivity.map((s) => h('tr', {}, h('td', {}, `${s.leakage_pct}%`), h('td', { class: 'num' }, usd(s.monthly_saving)), h('td', { class: 'num' }, s.payback_months ? `${s.payback_months} oy` : '—')))))),
    h('p', { class: 'caption' }, "Bu hisob-kitob va'da emas. Haqiqiy natija pilotda bazaviy o'lchov bilan aniqlanadi."),
    leadBlock());
}

function leadBlock() {
  const email = input({ type: 'email', autocomplete: 'email', placeholder: 'siz@kompaniya.uz' });
  const company = input({ autocomplete: 'organization' });
  const fe = field({ label: 'Email', input: email, required: true });
  return h('div', { class: 'card stack' }, h('h3', {}, 'PDF hisobotni olish'), h('div', { class: 'caption' }, "Email faqat shu hisobot va pilot taklifi bo'yicha aloqa uchun ishlatiladi."),
    fe, field({ label: 'Kompaniya (ixtiyoriy)', input: company }),
    btn('PDF yuklab olish', { variant: 'secondary', onClick: async () => {
      fe.setError(null);
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.value)) { fe.setError("Email noto'g'ri"); return; }
      try { await api.download('/api/v1/public/roi/report', 'fras-roi.pdf', { method: 'POST', body: { email: email.value, company: company.value || null, inputs: values() } }); }
      catch (e) { toast(errorText(e), 'error'); }
    } }));
}

root.append(h('div', { class: 'roi-page' },
  h('header', { class: 'row', style: { marginBottom: '16px' } }, h('span', { class: 'avatar', style: { background: 'var(--c-primary)', color: '#fff' } }, 'FR'),
    h('div', {}, h('strong', {}, 'FRAS'), h('div', { class: 'caption' }, 'Yuz orqali davomat — ROI kalkulyatori')), h('span', { style: { flex: 1 } }), h('a', { href: '/app/' }, 'Kirish')),
  h('h1', {}, 'Tizim sizga qancha tejaydi?'),
  h('p', { class: 'muted' }, "O'z raqamlaringizni kiriting. Biz siz kiritmagan qiymatlarni yashirincha taxmin qilmaymiz — har bir taxmin alohida ko'rsatiladi."),
  h('div', { class: 'roi-grid' }, h('div', { class: 'card stack' }, f.el, btn('Hisoblash', { size: 'l', onClick: calc })), result)));
