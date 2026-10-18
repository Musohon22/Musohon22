"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { loadDetail, online, useStore, useT } from "@/lib/store";
import type { PlanDetail } from "@/lib/types";
import { Check, Lock, X } from "../Icons";

/** "This plan comes after…": pick the plans that must be finished first. */
export function Dependencies({ plan, editable }: { plan: PlanDetail; editable: boolean }) {
  const t = useT();
  const planMap = useStore((s) => s.plans);
  const reachable = useStore((s) => s.online && !s.serverDown);
  const [pick, setPick] = useState("");

  const blockers = plan.blocked_by.map((id) => planMap[id]).filter(Boolean);
  const candidates = Object.values(planMap)
    .filter((p) => p.id !== plan.id && !plan.blocked_by.includes(p.id) && p.status !== "cancelled")
    .sort((a, b) => a.title.localeCompare(b.title));

  async function add(id: string) {
    setPick("");
    const ok = await online(() => api.post(`/api/plans/${plan.id}/dependencies`, { blocker_id: id }));
    if (ok) await loadDetail(plan.id);
  }

  async function remove(id: string) {
    const ok = await online(async () => {
      await api.del(`/api/plans/${plan.id}/dependencies/${id}`);
      return true;
    });
    if (ok) await loadDetail(plan.id);
  }

  return (
    <section className="flex flex-col gap-2">
      <h2 className="font-display text-2xl font-bold tracking-tight">{t("deps.title")}</h2>
      <p className="text-sm text-ink-muted">{t("deps.lead")}</p>
      {blockers.length === 0 && <p className="text-sm text-ink-3">{t("deps.none")}</p>}
      <ul className="flex flex-col gap-1.5">
        {blockers.map((b) => {
          const done = b.status === "done";
          return (
            <li key={b.id} className="flex items-center gap-2 rounded-xl border border-line-soft bg-paper-2 px-3 py-2">
              {done ? <Check size={16} className="text-ok" /> : <Lock size={16} className="text-warn-strong" />}
              <a href={`/plan/${b.id}`} className={`min-w-0 flex-1 truncate text-sm font-semibold ${done ? "text-ink-muted line-through" : ""}`}>{b.title}</a>
              {editable && (
                <button type="button" className="btn-icon h-8 w-8" aria-label={t("deps.remove", { title: b.title })} onClick={() => void remove(b.id)}>
                  <X size={15} />
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {editable && (
        <label>
          <span className="sr-only">{t("deps.add")}</span>
          <select className="field" value={pick} disabled={!reachable} onChange={(e) => e.target.value && void add(e.target.value)}>
            <option value="">{t("deps.add")}</option>
            {candidates.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select>
        </label>
      )}
    </section>
  );
}
