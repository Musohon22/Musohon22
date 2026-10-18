import { INTL_LOCALE } from "./i18n";
import type { Lang, Plan } from "./types";

const DAY = 86_400_000;

function parts(date: Date, tz: string) {
  const f = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  });
  const p: Record<string, string> = {};
  for (const { type, value } of f.formatToParts(date)) p[type] = value;
  return p;
}

function offsetMs(date: Date, tz: string): number {
  const p = parts(date, tz);
  const asUtc = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second);
  return asUtc - Math.floor(date.getTime() / 1000) * 1000;
}

/** "YYYY-MM-DD" of the given instant in the user's time zone. */
export function dayKey(date: Date | string, tz: string): string {
  const p = parts(typeof date === "string" ? new Date(date) : date, tz);
  return `${p.year}-${p.month}-${p.day}`;
}

export function addDays(key: string, n: number): string {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d) + n * DAY).toISOString().slice(0, 10);
}

/** ISO instant → value for <input type="datetime-local"> shown in the user's time zone. */
export function toLocalInput(iso: string | null, tz: string): string {
  if (!iso) return "";
  const p = parts(new Date(iso), tz);
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

/** <input type="datetime-local"> value interpreted in the user's time zone → ISO instant. */
export function fromLocalInput(value: string, tz: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value);
  if (!m) return null;
  const guess = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  let ts = guess - offsetMs(new Date(guess), tz);
  ts = guess - offsetMs(new Date(ts), tz); // second pass settles DST edges
  return new Date(ts).toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function fmtTime(iso: string, tz: string, lang: Lang): string {
  return new Intl.DateTimeFormat(INTL_LOCALE[lang], { timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(iso));
}

export function fmtDate(iso: string, tz: string, lang: Lang): string {
  return new Intl.DateTimeFormat(INTL_LOCALE[lang], { timeZone: tz, day: "numeric", month: "short" }).format(new Date(iso));
}

export function fmtDateTime(iso: string, tz: string, lang: Lang): string {
  return `${fmtDate(iso, tz, lang)}, ${fmtTime(iso, tz, lang)}`;
}

export type Zone = "overdue" | "today" | "tomorrow" | "week" | "later" | "none";

/** Which column / list section a plan belongs to, from its due date in the user's time zone. */
export function zoneOf(plan: Pick<Plan, "due_at" | "status" | "completed_at">, tz: string, now = new Date()): Zone {
  const today = dayKey(now, tz);
  const anchor = plan.status === "done" && plan.completed_at ? plan.completed_at : plan.due_at;
  if (!anchor) return "none";
  const day = dayKey(anchor, tz);
  const open = plan.status === "active" || plan.status === "returned";
  if (day < today) return open ? "overdue" : "none";
  if (day === today) return "today";
  if (day === addDays(today, 1)) return "tomorrow";
  if (day <= addDays(today, 7)) return "week";
  return "later";
}

export function isOverdue(plan: Pick<Plan, "due_at" | "status">, now = Date.now()): boolean {
  return !!plan.due_at && (plan.status === "active" || plan.status === "returned") && new Date(plan.due_at).getTime() < now;
}

/** Splits minutes into the largest sensible unit for display. */
export function durationParts(minutes: number): { unit: "minutes" | "hours" | "days"; n: number } {
  if (minutes < 60) return { unit: "minutes", n: Math.max(1, Math.round(minutes)) };
  if (minutes < 1440) return { unit: "hours", n: Math.round(minutes / 60) };
  return { unit: "days", n: Math.round(minutes / 1440) };
}

export function minutesSince(iso: string, now = Date.now()): number {
  return (now - new Date(iso).getTime()) / 60000;
}

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Tashkent";
  } catch {
    return "Asia/Tashkent";
  }
}
