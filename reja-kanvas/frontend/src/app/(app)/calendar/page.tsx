"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { freeSlot } from "@/lib/canvas";
import { INTL_LOCALE } from "@/lib/i18n";
import { createPlan, useStore, useT } from "@/lib/store";
import { addDays, dayKey, fmtTime, fromLocalInput } from "@/lib/time";
import type { Plan } from "@/lib/types";
import { CARD_BG } from "@/components/canvas/PlanCard";
import { ChevronLeft, Plus } from "@/components/Icons";

const DOT: Record<Plan["color"], string> = {
  yellow: "bg-[#F2C230]", mint: "bg-[#3DB37A]", lilac: "bg-[#7D6BE0]", peach: "bg-[#FF9B66]", sky: "bg-[#6B8CFF]", white: "bg-ink-muted",
};

function monthGrid(year: number, month: number): string[] {
  const first = new Date(Date.UTC(year, month, 1));
  const offset = (first.getUTCDay() + 6) % 7; // Monday first
  const start = new Date(Date.UTC(year, month, 1 - offset)).toISOString().slice(0, 10);
  return Array.from({ length: 42 }, (_, i) => addDays(start, i));
}

export default function CalendarPage() {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const planMap = useStore((s) => s.plans);
  const today = dayKey(new Date(), user.tz);
  const [cursor, setCursor] = useState(() => ({ y: +today.slice(0, 4), m: +today.slice(5, 7) - 1 }));
  const [selected, setSelected] = useState(today);
  const [draft, setDraft] = useState("");

  const byDay = useMemo(() => {
    const map: Record<string, Plan[]> = {};
    for (const p of Object.values(planMap)) {
      if (!p.due_at || p.status === "cancelled") continue;
      (map[dayKey(p.due_at, user.tz)] ??= []).push(p);
    }
    for (const list of Object.values(map)) list.sort((a, b) => a.due_at!.localeCompare(b.due_at!));
    return map;
  }, [planMap, user.tz]);
  const noDue = useMemo(() => Object.values(planMap).filter((p) => !p.due_at && p.status === "active").length, [planMap]);

  const days = monthGrid(cursor.y, cursor.m);
  const locale = INTL_LOCALE[lang];
  const monthLabel = new Intl.DateTimeFormat(locale, { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(Date.UTC(cursor.y, cursor.m, 1)));
  const longDay = (key: string) => new Intl.DateTimeFormat(locale, { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" }).format(new Date(`${key}T00:00:00Z`));
  const shift = (n: number) => setCursor(({ y, m }) => ({ y: y + Math.floor((m + n) / 12), m: (((m + n) % 12) + 12) % 12 }));

  function add(e: React.FormEvent) {
    e.preventDefault();
    const title = draft.trim();
    if (!title) return;
    // 09:00 on the chosen day, in the user's own time zone
    const due = fromLocalInput(`${selected}T09:00`, user.tz);
    const pos = freeSlot(Object.values(planMap), {});
    createPlan({ title: title.slice(0, 200), x: pos.x, y: pos.y, due_at: due });
    setDraft("");
  }

  const dayPlans = byDay[selected] ?? [];

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6 lg:flex-row">
      <section className="min-w-0 flex-1">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <h1 className="mr-auto font-display text-3xl font-extrabold capitalize tracking-tight">{monthLabel}</h1>
          <button type="button" className="btn-icon" aria-label={t("cal.prev")} onClick={() => shift(-1)}><ChevronLeft /></button>
          <button
            type="button"
            className="btn h-10"
            onClick={() => {
              setCursor({ y: +today.slice(0, 4), m: +today.slice(5, 7) - 1 });
              setSelected(today);
            }}
          >
            {t("cal.today")}
          </button>
          <button type="button" className="btn-icon" aria-label={t("cal.next")} onClick={() => shift(1)}><ChevronLeft className="rotate-180" /></button>
        </div>
        <div role="grid" aria-label={monthLabel} className="grid grid-cols-7 overflow-hidden rounded-2xl border border-line bg-line">
          {[0, 1, 2, 3, 4, 5, 6].map((d) => (
            <div key={d} role="columnheader" className="bg-paper-2 py-2 text-center text-xs font-bold text-ink-muted">{t(`wd.${d}` as "wd.0")}</div>
          ))}
          {days.map((key) => {
            const inMonth = +key.slice(5, 7) - 1 === cursor.m;
            const items = byDay[key] ?? [];
            const isToday = key === today;
            const isSel = key === selected;
            return (
              <button
                key={key}
                type="button"
                role="gridcell"
                aria-selected={isSel}
                aria-label={`${longDay(key)}${items.length ? `, ${items.length}` : ""}`}
                onClick={() => setSelected(key)}
                className={`mt-px flex min-h-[64px] flex-col gap-1 p-1.5 text-left sm:min-h-[104px] ${inMonth ? "bg-surface" : "bg-paper-2 text-ink-muted"} ${isSel ? "outline outline-2 -outline-offset-2 outline-accent" : ""}`}
              >
                <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${isToday ? "bg-accent text-white" : ""}`}>{+key.slice(8)}</span>
                <span className="hidden flex-col gap-0.5 sm:flex">
                  {items.slice(0, 3).map((p) => (
                    <span key={p.id} className={`card-scope truncate rounded-md px-1.5 py-0.5 text-[11px] font-semibold text-ink ${CARD_BG[p.color]} ${p.status === "done" ? "line-through opacity-60" : ""}`}>
                      {p.title}
                    </span>
                  ))}
                  {items.length > 3 && <span className="px-1 text-[11px] font-semibold text-ink-muted">{t("cal.more", { n: items.length - 3 })}</span>}
                </span>
                <span className="flex flex-wrap gap-0.5 sm:hidden" aria-hidden="true">
                  {items.slice(0, 4).map((p) => <span key={p.id} className={`h-1.5 w-1.5 rounded-full ${DOT[p.color]}`} />)}
                </span>
              </button>
            );
          })}
        </div>
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
              <Link href={`/plan/${p.id}`} className="flex items-center gap-3 rounded-xl border border-line bg-surface p-3 hover:border-line-strong">
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
