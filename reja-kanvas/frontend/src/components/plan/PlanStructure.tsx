"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { createPlan, updatePlan, useStore, useT } from "@/lib/store";
import type { Goal, PlanDetail } from "@/lib/types";
import { Check, Plus } from "../Icons";

const DURATIONS = [15, 30, 45, 60, 90, 120, 180, 240, 480];

/** Parent, sub-plans, goal and duration: where this plan sits in the bigger picture. */
export function PlanStructure({ plan, editable }: { plan: PlanDetail; editable: boolean }) {
  const t = useT();
  const planMap = useStore((s) => s.plans);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [childTitle, setChildTitle] = useState("");

  useEffect(() => {
    api.get<{ goals: Goal[] }>("/api/goals").then((r) => setGoals(r.goals)).catch(() => undefined);
  }, []);

  const candidates = Object.values(planMap).filter(
    (p) => p.id !== plan.id && p.board_id === plan.board_id && p.parent_id !== plan.id && p.status !== "cancelled",
  );
  const durationLabel = (m: number) => (m < 60 ? t("plan.minutesN", { n: m }) : t("plan.hoursN", { n: m / 60 }));

  function addChild(e: React.FormEvent) {
    e.preventDefault();
    const title = childTitle.trim();
    if (!title) return;
    createPlan({ title: title.slice(0, 200), x: plan.x + 40, y: plan.y + 220, parent_id: plan.id, board_id: plan.board_id, due_at: plan.due_at });
    setChildTitle("");
  }

  const children = [
    ...(plan.children ?? []),
    // children created on this device that the server has not returned yet
    ...Object.values(planMap)
      .filter((p) => p.parent_id === plan.id && !(plan.children ?? []).some((c) => c.id === p.id))
      .map((p) => ({ id: p.id, title: p.title, status: p.status, due_at: p.due_at })),
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <label className="flex flex-col gap-1.5">
        <span className="label">{t("plan.goalLink")}</span>
        <select className="field" disabled={!editable} value={plan.goal_id ?? ""} onChange={(e) => updatePlan(plan.id, { goal_id: e.target.value || null })}>
          <option value="">{t("plan.noGoal")}</option>
          {goals.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="label">{t("plan.duration")}</span>
        <select
          className="field"
          disabled={!editable}
          value={plan.duration_minutes ?? ""}
          onChange={(e) => updatePlan(plan.id, { duration_minutes: e.target.value ? Number(e.target.value) : null })}
        >
          <option value="">{t("plan.durationNone")}</option>
          {DURATIONS.map((m) => <option key={m} value={m}>{durationLabel(m)}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1.5 sm:col-span-2">
        <span className="label">{t("plan.parent")}</span>
        <select className="field" disabled={!editable} value={plan.parent_id ?? ""} onChange={(e) => updatePlan(plan.id, { parent_id: e.target.value || null })}>
          <option value="">{t("plan.noParent")}</option>
          {candidates.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
        </select>
      </label>
      <section className="flex flex-col gap-2 sm:col-span-2">
        <h3 className="label">{t("plan.children")}</h3>
        <ul className="flex flex-col gap-1.5">
          {children.map((c) => (
            <li key={c.id}>
              <Link href={`/plan/${c.id}`} className="flex items-center gap-2 rounded-lg border border-line-soft bg-paper-2 px-3 py-2 text-sm">
                <span className={`flex h-5 w-5 items-center justify-center rounded border-2 ${c.status === "done" ? "border-ok bg-ok text-white" : "border-line-strong"}`}>
                  {c.status === "done" && <Check size={12} />}
                </span>
                <span className={`min-w-0 flex-1 truncate font-semibold ${c.status === "done" ? "text-ink-muted line-through" : ""}`}>{c.title}</span>
              </Link>
            </li>
          ))}
        </ul>
        {editable && (
          <form onSubmit={addChild} className="flex items-center gap-2">
            <Plus size={16} className="text-ink-muted" />
            <label className="flex-1">
              <span className="sr-only">{t("plan.addChild")}</span>
              <input className="h-10 w-full bg-transparent text-sm outline-none" value={childTitle} maxLength={200} placeholder={t("plan.addChild")} onChange={(e) => setChildTitle(e.target.value)} />
            </label>
          </form>
        )}
      </section>
    </div>
  );
}
