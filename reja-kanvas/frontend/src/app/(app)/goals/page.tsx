"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { online, useStore, useT } from "@/lib/store";
import { dayKey } from "@/lib/time";
import type { Color, Goal } from "@/lib/types";
import { CARD_BG } from "@/components/canvas/PlanCard";
import { Plus } from "@/components/Icons";

const COLORS: Color[] = ["sky", "mint", "lilac", "peach", "yellow", "white"];

export default function GoalsPage() {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const planMap = useStore((s) => s.plans);
  const [goals, setGoals] = useState<Goal[] | null>(null);
  const [form, setForm] = useState({ title: "", description: "", target_date: "", color: "sky" as Color });
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    api.get<{ goals: Goal[] }>("/api/goals").then((r) => setGoals(r.goals)).catch(() => setGoals((g) => g ?? []));
  }, []);
  useEffect(load, [load]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const g = await online(() => api.post<Goal>("/api/goals", { ...form, title: form.title.trim(), target_date: form.target_date || null }));
    if (g) {
      setGoals((list) => [...(list ?? []), g]);
      setForm({ title: "", description: "", target_date: "", color: "sky" });
      setAdding(false);
    }
  }

  async function archive(g: Goal) {
    if (await online(() => api.patch(`/api/goals/${g.id}`, { archived: true }))) setGoals((list) => list?.filter((x) => x.id !== g.id) ?? null);
  }

  const today = dayKey(new Date(), user.tz);
  const daysLeft = (d: string) => Math.round((Date.parse(d) - Date.parse(today)) / 86_400_000);

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-4 py-8 sm:px-6">
      <div className="flex flex-wrap items-end gap-3">
        <div className="mr-auto">
          <h1 className="font-display text-3xl font-extrabold tracking-tight">{t("goals.title")}</h1>
          <p className="mt-1 text-ink-3">{t("goals.lead")}</p>
        </div>
        <button type="button" className="btn-primary" onClick={() => setAdding((a) => !a)}><Plus size={16} />{t("goals.new")}</button>
      </div>

      {adding && (
        <form onSubmit={create} className="grid gap-3 rounded-2xl border border-line bg-surface p-5 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5 sm:col-span-2">
            <span className="label">{t("goals.name")}</span>
            <input className="field" required maxLength={120} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1.5 sm:col-span-2">
            <span className="label">{t("goals.description")}</span>
            <textarea className="field h-auto py-2" rows={2} maxLength={2000} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="label">{t("goals.target")}</span>
            <input type="date" className="field" value={form.target_date} onChange={(e) => setForm({ ...form, target_date: e.target.value })} />
          </label>
          <fieldset className="flex flex-col gap-1.5">
            <legend className="label mb-1.5">{t("plan.color")}</legend>
            <div className="flex gap-1.5">
              {COLORS.map((c) => (
                <button key={c} type="button" aria-label={c} aria-pressed={form.color === c} onClick={() => setForm({ ...form, color: c })}
                  className={`h-8 w-8 rounded-full ring-1 ring-black/10 ${CARD_BG[c]} ${form.color === c ? "ring-2 ring-ink ring-offset-2" : ""}`} />
              ))}
            </div>
          </fieldset>
          <button className="btn-dark sm:col-span-2" disabled={!form.title.trim()}>{t("common.save")}</button>
        </form>
      )}

      {goals?.length === 0 && !adding && <p className="rounded-2xl border border-dashed border-line-strong p-8 text-center text-ink-muted">{t("goals.empty")}</p>}
      <ul className="grid gap-4 md:grid-cols-2">
        {goals?.map((g) => {
          const linked = Object.values(planMap).filter((p) => p.goal_id === g.id && p.status !== "done" && p.status !== "cancelled").slice(0, 4);
          const left = g.target_date ? daysLeft(g.target_date) : null;
          return (
            <li key={g.id} className={`card-scope flex flex-col gap-3 rounded-2xl p-5 text-ink shadow-card ${CARD_BG[g.color]}`}>
              <div className="flex items-start justify-between gap-3">
                <h2 className="font-display text-xl font-bold leading-tight">{g.title}</h2>
                {left !== null && (
                  <span className={`chip whitespace-nowrap ${left < 0 ? "bg-warn-strong text-white" : "bg-surface/70"}`}>{left < 0 ? t("goals.overdue") : t("goals.daysLeft", { n: left })}</span>
                )}
              </div>
              {g.description && <p className="text-sm text-ink-2">{g.description}</p>}
              <div>
                <div className="h-2 rounded-full bg-black/10" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(g.progress * 100)} aria-label={g.title}>
                  <div className="h-2 rounded-full bg-ink" style={{ width: `${g.progress * 100}%` }} />
                </div>
                <div className="mt-1 text-xs text-ink-3">{t("goals.progress", { done: g.plans_done, total: g.plans_total })}</div>
              </div>
              {linked.length > 0 && (
                <ul className="flex flex-col gap-1 text-sm">
                  {linked.map((p) => <li key={p.id}><Link href={`/plan/${p.id}`} className="underline-offset-2 hover:underline">• {p.title}</Link></li>)}
                </ul>
              )}
              <button type="button" className="self-start text-xs font-semibold text-ink-3 underline" onClick={() => void archive(g)}>{t("goals.archive")}</button>
            </li>
          );
        })}
      </ul>
    </main>
  );
}
