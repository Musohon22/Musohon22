"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { loadPlans, loadStats, online, settle, useStore, useT } from "@/lib/store";
import { dayKey, fmtDateTime } from "@/lib/time";
import type { Plan } from "@/lib/types";
import { Dialog } from "./Dialog";
import { Calendar } from "./Icons";

const SEEN_KEY = "reja.overdueSeen";

/** Once a day: plans that slipped past their day, with one-tap ways to move on. No blame. */
export function OverdueDialog() {
  const t = useT();
  const user = useStore((s) => s.user);
  const lang = useStore((s) => s.lang);
  const reachable = useStore((s) => s.online && !s.serverDown);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [open, setOpen] = useState(false);
  const [dates, setDates] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!user || !reachable) return;
    const today = dayKey(new Date(), user.tz);
    let seen: string | null = null;
    try {
      seen = localStorage.getItem(SEEN_KEY);
    } catch {
      /* ignore */
    }
    if (seen === today) return;
    api
      .get<{ plans: Plan[] }>("/api/plans/overdue")
      .then(({ plans }) => {
        if (plans.length) {
          setPlans(plans);
          setOpen(true);
        }
      })
      .catch(() => undefined);
  }, [user, reachable]);

  function close() {
    setOpen(false);
    try {
      localStorage.setItem(SEEN_KEY, dayKey(new Date(), user!.tz));
    } catch {
      /* ignore */
    }
  }

  async function act(ids: string[], action: "today" | "date" | "cancel", date?: string) {
    for (const id of ids) if (!(await settle(id))) return;
    const res = await online(() => api.post<{ plans: Plan[] }>("/api/plans/reschedule", { ids, action, date }));
    if (!res) return;
    const left = plans.filter((p) => !ids.includes(p.id));
    setPlans(left);
    void loadPlans();
    void loadStats();
    if (!left.length) close();
  }

  if (!user) return null;
  return (
    <Dialog open={open} onClose={close} title={t("overdue.title", { n: plans.length })} wide>
      <p className="-mt-2 text-ink-3">{t("overdue.lead")}</p>
      <ul className="flex max-h-[50vh] flex-col gap-2 overflow-y-auto">
        {plans.map((p) => (
          <li key={p.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-white p-3">
            <div className="min-w-0 flex-1 basis-48">
              <div className="truncate font-bold">{p.title}</div>
              <div className="text-xs text-ink-muted">{t("overdue.was", { date: fmtDateTime(p.due_at!, user.tz, lang) })}</div>
            </div>
            <button type="button" className="btn h-10" onClick={() => void act([p.id], "today")}>{t("overdue.toToday")}</button>
            <label className="flex items-center gap-1">
              <span className="sr-only">{t("overdue.pickDate")}</span>
              <Calendar size={16} className="text-ink-muted" />
              <input
                type="date"
                className="field h-10 w-[150px]"
                min={dayKey(new Date(), user.tz)}
                value={dates[p.id] ?? ""}
                onChange={(e) => {
                  setDates((d) => ({ ...d, [p.id]: e.target.value }));
                  if (e.target.value) void act([p.id], "date", e.target.value);
                }}
              />
            </label>
            <button type="button" className="btn h-10 text-ink-3" onClick={() => void act([p.id], "cancel")}>{t("overdue.cancel")}</button>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" className="btn" onClick={close}>{t("overdue.later")}</button>
        <button type="button" className="btn-primary" onClick={() => void act(plans.map((p) => p.id), "today")}>{t("overdue.allToday")}</button>
      </div>
    </Dialog>
  );
}
