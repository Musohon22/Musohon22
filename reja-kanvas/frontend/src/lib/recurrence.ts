import type { MessageKey, Vars } from "./i18n";
import type { Priority, Recurrence } from "./types";

type T = (key: MessageKey, vars?: Vars) => string;

/** "Every week · Mo, Th · until 1 Dec" in the user's language. */
export function describeRecurrence(r: Recurrence, t: T, fmtDay?: (iso: string) => string): string {
  const n = r.interval || 1;
  const base =
    r.freq === "daily" ? (n === 1 ? t("rec.daily") : t("rec.everyNDays", { n }))
    : r.freq === "weekly" ? (n === 1 ? t("rec.weekly") : t("rec.everyNWeeks", { n }))
    : n === 1 ? t("rec.monthly") : t("rec.everyNMonths", { n });
  const parts = [base];
  if (r.freq === "weekly" && r.weekdays.length) parts.push(r.weekdays.map((d) => t(`wd.${d}` as MessageKey)).join(", "));
  if (r.until) parts.push(t("rec.untilDate", { date: fmtDay ? fmtDay(r.until) : r.until }));
  return parts.join(" · ");
}

export const PRIORITIES: Priority[] = ["urgent", "high", "normal", "low"];

/** Colour of the small priority flag; "normal" shows none. Distinct in lightness, not just hue. */
export const PRIORITY_STYLE: Record<Priority, string> = {
  urgent: "bg-warn-strong text-white",
  high: "bg-warn-soft text-warn-ink",
  normal: "",
  low: "bg-paper-3 text-ink-3",
};
