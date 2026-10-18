"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { freeSlot } from "@/lib/canvas";
import { matches } from "@/lib/filter";
import { INTL_LOCALE } from "@/lib/i18n";
import { createPlan, updatePlan, useStore, useT } from "@/lib/store";
import { addDays, dayKey, fmtTime, fromLocalInput, toLocalInput } from "@/lib/time";
import type { Plan } from "@/lib/types";
import { CARD_BG } from "@/components/canvas/PlanCard";
import { FilterBar } from "@/components/FilterBar";
import { ChevronLeft, Plus } from "@/components/Icons";

const DOT: Record<Plan["color"], string> = {
  yellow: "bg-[#F2C230]", mint: "bg-[#3DB37A]", lilac: "bg-[#7D6BE0]", peach: "bg-[#FF9B66]", sky: "bg-[#6B8CFF]", white: "bg-ink-muted",
};
const HOURS = Array.from({ length: 16 }, (_, i) => i + 7); // 07:00–22:00
const HOUR_PX = 48;

function monthGrid(year: number, month: number): string[] {
  const first = new Date(Date.UTC(year, month, 1));
  const offset = (first.getUTCDay() + 6) % 7; // Monday first
  const start = new Date(Date.UTC(year, month, 1 - offset)).toISOString().slice(0, 10);
  return Array.from({ length: 42 }, (_, i) => addDays(start, i));
}

function weekStart(key: string): string {
  const d = new Date(`${key}T00:00:00Z`);
  return addDays(key, -((d.getUTCDay() + 6) % 7));
}

/** Moves a plan to another day, keeping its time of day (in the user's time zone). */
function moveToDay(plan: Plan, day: string, tz: string, hour?: number) {
  const time = plan.due_at ? toLocalInput(plan.due_at, tz).slice(11) : "09:00";
  const hh = hour !== undefined ? `${String(hour).padStart(2, "0")}:${time.slice(3)}` : time;
  const due = fromLocalInput(`${day}T${hh}`, tz);
  if (due && due !== plan.due_at) updatePlan(plan.id, { due_at: due });
}

export default function CalendarPage() {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const planMap = useStore((s) => s.plans);
  const filter = useStore((s) => s.filter);
  const today = dayKey(new Date(), user.tz);
  const [mode, setMode] = useState<"month" | "week">("month");
  const [cursor, setCursor] = useState(today);
  const [selected, setSelected] = useState(today);
  const [draft, setDraft] = useState("");
  const [over, setOver] = useState<string | null>(null);

  const visible = useMemo(
    () => Object.values(planMap).filter((p) => p.status !== "cancelled" && matches(p, filter, user.tz, user.id)),
    [planMap, filter, user.tz, user.id],
  );
  const byDay = useMemo(() => {
    const map: Record<string, Plan[]> = {};
    for (const p of visible) if (p.due_at) (map[dayKey(p.due_at, user.tz)] ??= []).push(p);
    for (const list of Object.values(map)) list.sort((a, b) => a.due_at!.localeCompare(b.due_at!));
    return map;
  }, [visible, user.tz]);
  const noDue = visible.filter((p) => !p.due_at && p.status === "active").length;

  const locale = INTL_LOCALE[lang];
  const y = +cursor.slice(0, 4);
  const m = +cursor.slice(5, 7) - 1;
  const fmt = (key: string, o: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat(locale, { ...o, timeZone: "UTC" }).format(new Date(`${key}T00:00:00Z`));
  const longDay = (key: string) => fmt(key, { weekday: "long", day: "numeric", month: "long" });
  const ws = weekStart(cursor);
  const week = Array.from({ length: 7 }, (_, i) => addDays(ws, i));
  const title = mode === "month" ? fmt(`${cursor.slice(0, 7)}-01`, { month: "long", year: "numeric" }) : `${fmt(week[0], { day: "numeric", month: "short" })} – ${fmt(week[6], { day: "numeric", month: "short", year: "numeric" })}`;

  function shift(n: number) {
    if (mode === "week") return setCursor(addDays(cursor, n * 7));
    const d = new Date(Date.UTC(y, m + n, 1));
    setCursor(d.toISOString().slice(0, 10));
  }

  function add(e: React.FormEvent) {
    e.preventDefault();
    const title = draft.trim();
    if (!title) return;
    const due = fromLocalInput(`${selected}T09:00`, user.tz);
    const pos = freeSlot(Object.values(planMap), {});
    createPlan({ title: title.slice(0, 200), x: pos.x, y: pos.y, due_at: due });
    setDraft("");
  }

  const dropProps = (day: string, hour?: number) => ({
    onDragOver: (e: React.DragEvent) => {
      e.preventDefault();
      setOver(hour === undefined ? day : `${day}-${hour}`);
    },
    onDragLeave: () => setOver(null),
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      setOver(null);
      const p = planMap[e.dataTransfer.getData("text/plan")];
      if (p && p.my_role !== "viewer") moveToDay(p, day, user.tz, hour);
    },
  });
  const dragProps = (p: Plan) => ({
    draggable: p.status === "active" || p.status === "returned",
    onDragStart: (e: React.DragEvent) => e.dataTransfer.setData("text/plan", p.id),
  });

  const dayPlans = byDay[selected] ?? [];

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6 lg:flex-row">
      <section className="min-w-0 flex-1">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <h1 className="mr-auto font-display text-3xl font-extrabold capitalize tracking-tight">{title}</h1>
          <div role="radiogroup" aria-label={t("nav.calendar")} className="flex rounded-xl bg-paper-3 p-1">
            {(["month", "week"] as const).map((v) => (
              <button key={v} type="button" role="radio" aria-checked={mode === v} onClick={() => setMode(v)} className={`h-9 rounded-lg px-3 text-sm font-bold ${mode === v ? "bg-surface shadow-sm" : "text-ink-3"}`}>
                {t(v === "month" ? "cal.month" : "cal.week")}
              </button>
            ))}
          </div>
          <button type="button" className="btn-icon" aria-label={mode === "week" ? t("cal.prevWeek") : t("cal.prev")} onClick={() => shift(-1)}><ChevronLeft /></button>
          <button type="button" className="btn h-10" onClick={() => { setCursor(today); setSelected(today); }}>{t("cal.today")}</button>
          <button type="button" className="btn-icon" aria-label={mode === "week" ? t("cal.nextWeek") : t("cal.next")} onClick={() => shift(1)}><ChevronLeft className="rotate-180" /></button>
        </div>
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <FilterBar />
          <span className="text-xs text-ink-muted">{t("cal.dropHint")}</span>
        </div>

        {mode === "month" ? (
          <div role="grid" aria-label={title} className="grid grid-cols-7 overflow-hidden rounded-2xl border border-line bg-line">
            {[0, 1, 2, 3, 4, 5, 6].map((d) => (
              <div key={d} role="columnheader" className="bg-paper-2 py-2 text-center text-xs font-bold text-ink-muted">{t(`wd.${d}` as "wd.0")}</div>
            ))}
            {monthGrid(y, m).map((key) => {
              const inMonth = +key.slice(5, 7) - 1 === m;
              const items = byDay[key] ?? [];
              return (
                <div
                  key={key}
                  role="gridcell"
                  aria-selected={key === selected}
                  {...dropProps(key)}
                  className={`mt-px flex min-h-[64px] flex-col gap-1 p-1.5 sm:min-h-[108px] ${inMonth ? "bg-surface" : "bg-paper-2 text-ink-muted"} ${key === selected ? "outline outline-2 -outline-offset-2 outline-accent" : ""} ${over === key ? "bg-accent-soft" : ""}`}
                >
                  <button
                    type="button"
                    aria-label={`${longDay(key)}${items.length ? `, ${items.length}` : ""}`}
                    onClick={() => setSelected(key)}
                    className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${key === today ? "bg-accent text-white" : "hover:bg-paper-3"}`}
                  >
                    {+key.slice(8)}
                  </button>
                  <span className="hidden flex-col gap-0.5 sm:flex">
                    {items.slice(0, 3).map((p) => (
                      <Link
                        key={p.id}
                        href={`/plan/${p.id}`}
                        {...dragProps(p)}
                        className={`card-scope truncate rounded-md px-1.5 py-0.5 text-[11px] font-semibold text-ink ${CARD_BG[p.color]} ${p.status === "done" ? "line-through opacity-60" : ""}`}
                      >
                        {p.title}
                      </Link>
                    ))}
                    {items.length > 3 && (
                      <button type="button" onClick={() => setSelected(key)} className="px-1 text-left text-[11px] font-semibold text-ink-muted">{t("cal.more", { n: items.length - 3 })}</button>
                    )}
                  </span>
                  <span className="flex flex-wrap gap-0.5 sm:hidden" aria-hidden="true">
                    {items.slice(0, 4).map((p) => <span key={p.id} className={`h-1.5 w-1.5 rounded-full ${DOT[p.color]}`} />)}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="overflow-x-auto rounded-2xl border border-line bg-surface">
            <div className="grid min-w-[760px] grid-cols-[56px_repeat(7,minmax(0,1fr))]">
              <div />
              {week.map((d) => (
                <button key={d} type="button" onClick={() => setSelected(d)} className={`border-b border-l border-line-soft py-2 text-center text-xs font-bold ${d === today ? "text-accent-ink" : "text-ink-muted"} ${d === selected ? "bg-accent-soft/60" : ""}`}>
                  {fmt(d, { weekday: "short", day: "numeric" })}
                </button>
              ))}
              {HOURS.map((h) => (
                <div key={h} className="contents">
                  <div className="border-t border-line-soft pr-2 pt-1 text-right font-mono text-[11px] text-ink-muted" style={{ height: HOUR_PX }}>{String(h).padStart(2, "0")}:00</div>
                  {week.map((d) => (
                    <div key={d} {...dropProps(d, h)} className={`relative border-l border-t border-line-soft ${over === `${d}-${h}` ? "bg-accent-soft" : ""}`} style={{ height: HOUR_PX }}>
                      {(byDay[d] ?? [])
                        .filter((p) => +toLocalInput(p.due_at, user.tz).slice(11, 13) === h)
                        .map((p) => {
                          const minute = +toLocalInput(p.due_at, user.tz).slice(14, 16);
                          const height = Math.max(22, ((p.duration_minutes ?? 30) / 60) * HOUR_PX - 2);
                          return (
                            <Link
                              key={p.id}
                              href={`/plan/${p.id}`}
                              {...dragProps(p)}
                              title={`${fmtTime(p.due_at!, user.tz, lang)} ${p.title}`}
                              className={`card-scope absolute inset-x-1 z-10 overflow-hidden rounded-md px-1.5 py-0.5 text-[11px] font-semibold leading-tight text-ink shadow-sm ${CARD_BG[p.color]} ${p.status === "done" ? "opacity-60" : ""}`}
                              style={{ top: (minute / 60) * HOUR_PX + 1, height }}
                            >
                              <span className="font-mono">{fmtTime(p.due_at!, user.tz, lang)}</span> {p.title}
                            </Link>
                          );
                        })}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        )}
        {noDue > 0 && <p className="mt-3 text-sm text-ink-muted">{t("cal.noDue", { n: noDue })} · <Link href="/list" className="font-semibold underline">{t("nav.list")}</Link></p>}
      </section>

      <aside className="flex w-full flex-col gap-4 lg:w-80 lg:flex-none">
        <h2 className="font-display text-xl font-bold capitalize">{longDay(selected)}</h2>
        <form onSubmit={add} className="flex gap-2">
          <label className="flex-1">
            <span className="sr-only">{t("cal.add", { date: longDay(selected) })}</span>
            <input className="field" value={draft} maxLength={200} placeholder={t("cal.add", { date: longDay(selected) })} onChange={(e) => setDraft(e.target.value)} />
          </label>
          <button className="btn-primary w-11 px-0" aria-label={t("cal.add", { date: longDay(selected) })} disabled={!draft.trim()}><Plus /></button>
        </form>
        <ul className="flex flex-col gap-2">
          {dayPlans.length === 0 && <li className="text-sm text-ink-muted">{t("today.nothingNext")}</li>}
          {dayPlans.map((p) => (
            <li key={p.id}>
              <Link href={`/plan/${p.id}`} {...dragProps(p)} className="flex items-center gap-3 rounded-xl border border-line bg-surface p-3 hover:border-line-strong">
                <span aria-hidden="true" className={`h-8 w-1.5 flex-none rounded-full ${DOT[p.color]}`} />
                <span className="min-w-0 flex-1">
                  <span className={`block truncate font-semibold ${p.status === "done" ? "text-ink-muted line-through" : ""}`}>{p.title}</span>
                  <span className="text-xs text-ink-muted">{fmtTime(p.due_at!, user.tz, lang)}{p.status !== "active" ? ` · ${t(`status.${p.status}`)}` : ""}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </aside>
    </main>
  );
}
