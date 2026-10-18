"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { online, storeDetail, toast, useT } from "@/lib/store";
import { durationParts } from "@/lib/time";
import type { PlanDetail } from "@/lib/types";
import { Clock } from "../Icons";

const POMODORO = 25 * 60;

/** Start/stop time tracking on a plan, with a 25-minute focus countdown and a break reminder. */
export function FocusTimer({ plan }: { plan: PlanDetail }) {
  const t = useT();
  const [now, setNow] = useState(() => Date.now());
  const running = !!plan.timer_started_at;
  const startedAt = plan.timer_started_at ? new Date(plan.timer_started_at).getTime() : 0;
  const elapsed = running ? Math.max(0, Math.floor((now - startedAt) / 1000)) : 0;
  const left = Math.max(0, POMODORO - elapsed);

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [running]);

  useEffect(() => {
    if (running && elapsed === POMODORO) {
      toast(t("timer.doneNotice"), { tone: "success", ms: 15000 });
      if (typeof Notification !== "undefined" && Notification.permission === "granted") new Notification("Reja", { body: t("timer.doneNotice"), icon: "/icon.svg" });
    }
  }, [running, elapsed, t]);

  async function toggle() {
    const d = await online(() => api.post<PlanDetail>(`/api/plans/${plan.id}/timer/${running ? "stop" : "start"}`));
    if (d) storeDetail({ ...plan, timer_started_at: d.timer_started_at, tracked_seconds: d.tracked_seconds });
  }

  const total = plan.tracked_seconds + elapsed;
  const tp = durationParts(total / 60);
  const mm = String(Math.floor(left / 60)).padStart(2, "0");
  const ss = String(left % 60).padStart(2, "0");
  const canRun = plan.status === "active" || plan.status === "returned";

  return (
    <section aria-labelledby="timer-title" className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-4">
      <h2 id="timer-title" className="eyebrow flex items-center gap-2"><Clock size={14} />{t("timer.title")}</h2>
      <div className="flex items-center gap-4">
        <div className="relative h-16 w-16 flex-none">
          <svg viewBox="0 0 64 64" className="h-16 w-16 -rotate-90" aria-hidden="true">
            <circle cx="32" cy="32" r="28" fill="none" strokeWidth="6" className="stroke-line-soft" />
            <circle cx="32" cy="32" r="28" fill="none" strokeWidth="6" strokeLinecap="round" className="stroke-accent" strokeDasharray={`${(1 - left / POMODORO) * 176} 176`} />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center font-mono text-xs font-bold" aria-live="off">{running ? `${mm}:${ss}` : "25:00"}</span>
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          <span className="text-sm text-ink-3">{running ? t("timer.left", { m: mm, s: ss }) : t("timer.pomodoro")}</span>
          {total > 0 && <span className="text-xs text-ink-muted">{t("timer.tracked", { d: t(`common.${tp.unit}`, { n: tp.n }) })}</span>}
        </div>
      </div>
      {canRun && plan.my_role === "owner" && (
        <button type="button" onClick={() => void toggle()} className={running ? "btn" : "btn-dark"}>
          {running ? t("timer.stop") : t("timer.start")}
        </button>
      )}
    </section>
  );
}
