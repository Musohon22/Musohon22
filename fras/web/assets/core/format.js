// Formatting helpers: dates in the site time zone, durations "7 s 45 daq", relative times.
export const DEFAULT_TZ = 'Asia/Tashkent';

export function fmtDate(v, tz = DEFAULT_TZ) {
  if (!v) return '—';
  const dayOnly = typeof v === 'string' && v.length === 10;
  const d = dayOnly ? new Date(v + 'T12:00:00Z') : new Date(v);
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', { timeZone: dayOnly ? 'UTC' : tz, day: '2-digit', month: '2-digit', year: 'numeric' })
    .formatToParts(d).map((x) => [x.type, x.value]));
  return `${p.day}.${p.month}.${p.year}`;
}
export function fmtTime(v, tz = DEFAULT_TZ, seconds = false) {
  if (!v) return '—';
  return new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}), hourCycle: 'h23' }).format(new Date(v));
}
export function fmtDateTime(v, tz = DEFAULT_TZ) { return v ? `${fmtDate(v, tz)} ${fmtTime(v, tz)}` : '—'; }
export function fmtDuration(min) {
  if (min === null || min === undefined) return '—';
  const h = Math.floor(min / 60), m = Math.round(min % 60);
  return `${h} s ${String(m).padStart(2, '0')} daq`;
}
export function fmtHours(min) { return min ? (min / 60).toFixed(1) : '0'; }
export function fmtNumber(n) { return n === null || n === undefined ? '—' : new Intl.NumberFormat('ru-RU').format(n); }
export function fmtMoney(cents, cur = 'USD') { return `${cur === 'USD' ? '$' : ''}${(cents / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }
export function relTime(v) {
  if (!v) return '—';
  const s = Math.round((Date.now() - new Date(v).getTime()) / 1000);
  if (s < 60) return `${Math.max(s, 0)} s oldin`;
  if (s < 3600) return `${Math.round(s / 60)} daq oldin`;
  if (s < 86400) return `${Math.round(s / 3600)} soat oldin`;
  return `${Math.round(s / 86400)} kun oldin`;
}
export function todayISO(tz = DEFAULT_TZ) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}
export function addDays(iso, n) { const d = new Date(iso + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); }
export function monthISO(iso) { return iso.slice(0, 7); }
export function daysBetween(a, b) { const out = []; for (let d = a; d <= b; d = addDays(d, 1)) out.push(d); return out; }
export function weekday(iso) { return new Date(iso + 'T12:00:00Z').getUTCDay(); }
export const WEEKDAYS = ['Ya', 'Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh'];
export function localToUTC(dateISO, hhmm, tz = DEFAULT_TZ) {
  // convert a wall-clock time in tz to a UTC ISO string (works for zones without DST changes on that day)
  const guess = new Date(`${dateISO}T${hhmm}:00Z`);
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit', hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(guess);
  const p = Object.fromEntries(parts.map((x) => [x.type, x.value]));
  const asLocal = new Date(`${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:00Z`);
  return new Date(guess.getTime() - (asLocal.getTime() - guess.getTime())).toISOString().replace('.000Z', 'Z');
}
export function initials(name = '') { return name.split(/\s+/).filter(Boolean).slice(0, 2).map((s) => s[0]).join('').toUpperCase(); }
