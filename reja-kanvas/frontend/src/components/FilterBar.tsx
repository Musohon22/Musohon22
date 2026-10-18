"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { filterCount } from "@/lib/filter";
import { PRIORITIES } from "@/lib/recurrence";
import { EMPTY_FILTER, online, setFilter, setSavedFilters, useStore, useT } from "@/lib/store";
import type { FilterQuery, PlanStatus, SavedFilter } from "@/lib/types";
import { X } from "./Icons";

const STATUSES: PlanStatus[] = ["active", "pending_approval", "returned", "done", "cancelled"];

function Toggle({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={`h-9 rounded-lg border px-2.5 text-sm font-semibold ${on ? "border-accent bg-accent-soft text-accent-ink" : "border-line bg-surface text-ink-2"}`}
    >
      {children}
    </button>
  );
}

/** One filter for canvas, list, board and calendar; saved filters live on the server. */
export function FilterBar({ teamMode = false }: { teamMode?: boolean }) {
  const t = useT();
  const filter = useStore((s) => s.filter);
  const saved = useStore((s) => s.savedFilters);
  const planMap = useStore((s) => s.plans);
  const [open, setOpen] = useState(false);
  const tags = useMemo(() => Array.from(new Set(Object.values(planMap).map((p) => p.tag).filter(Boolean) as string[])).sort().slice(0, 30), [planMap]);
  const n = filterCount(filter);
  const toggle = <K extends "tags" | "priorities" | "statuses">(key: K, v: FilterQuery[K][number]) =>
    setFilter({ ...filter, [key]: (filter[key] as string[]).includes(v as string) ? (filter[key] as string[]).filter((x) => x !== v) : [...filter[key], v] });

  async function save() {
    const name = window.prompt(t("filter.name"));
    if (!name?.trim()) return;
    const f = await online(() => api.post<SavedFilter>("/api/filters", { name: name.trim().slice(0, 60), query: filter }));
    if (f) setSavedFilters([...saved, f]);
  }

  async function remove(f: SavedFilter) {
    const ok = await online(async () => {
      await api.del(`/api/filters/${f.id}`);
      return true;
    });
    if (ok) setSavedFilters(saved.filter((x) => x.id !== f.id));
  }

  return (
    <div className="relative flex flex-wrap items-center gap-2">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={`h-10 rounded-xl border px-3 text-sm font-bold ${n ? "border-accent bg-accent-soft text-accent-ink" : "border-line bg-surface"}`}
      >
        {n ? t("filter.active", { n }) : t("filter.title")}
      </button>
      {saved.map((f) => (
        <span key={f.id} className="flex items-center rounded-xl border border-line bg-surface">
          <button type="button" className="h-10 px-3 text-sm font-semibold" onClick={() => setFilter({ ...EMPTY_FILTER, ...f.query })}>{f.name}</button>
          <button type="button" aria-label={t("filter.delete", { name: f.name })} className="flex h-10 w-8 items-center justify-center text-ink-muted" onClick={() => void remove(f)}>
            <X size={14} />
          </button>
        </span>
      ))}
      {n > 0 && <button type="button" className="h-10 px-2 text-sm font-semibold text-ink-muted underline" onClick={() => setFilter(EMPTY_FILTER)}>{t("filter.clear")}</button>}
      {open && (
        <div className="absolute left-0 top-12 z-30 flex w-[min(92vw,420px)] flex-col gap-4 rounded-2xl border border-line bg-paper-2 p-4 shadow-lift">
          <label className="flex flex-col gap-1.5">
            <span className="label">{t("canvas.search")}</span>
            <input className="field" value={filter.text} onChange={(e) => setFilter({ ...filter, text: e.target.value })} />
          </label>
          <fieldset className="flex flex-col gap-1.5">
            <legend className="label mb-1">{t("plan.priority")}</legend>
            <div className="flex flex-wrap gap-1.5">{PRIORITIES.map((p) => <Toggle key={p} on={filter.priorities.includes(p)} onClick={() => toggle("priorities", p)}>{t(`priority.${p}`)}</Toggle>)}</div>
          </fieldset>
          <fieldset className="flex flex-col gap-1.5">
            <legend className="label mb-1">{t("filter.status")}</legend>
            <div className="flex flex-wrap gap-1.5">{STATUSES.map((s) => <Toggle key={s} on={filter.statuses.includes(s)} onClick={() => toggle("statuses", s)}>{t(`status.${s}`)}</Toggle>)}</div>
          </fieldset>
          {tags.length > 0 && (
            <fieldset className="flex flex-col gap-1.5">
              <legend className="label mb-1">{t("filter.tags")}</legend>
              <div className="flex flex-wrap gap-1.5">{tags.map((tg) => <Toggle key={tg} on={filter.tags.includes(tg)} onClick={() => toggle("tags", tg)}>{tg}</Toggle>)}</div>
            </fieldset>
          )}
          <label className="flex flex-col gap-1.5">
            <span className="label">{t("filter.due")}</span>
            <select className="field" value={filter.due ?? ""} onChange={(e) => setFilter({ ...filter, due: (e.target.value || null) as FilterQuery["due"] })}>
              <option value="">{t("filter.any")}</option>
              <option value="overdue">{t("list.overdue")}</option>
              <option value="today">{t("list.today")}</option>
              <option value="week">{t("list.week")}</option>
              <option value="none">{t("list.noDue")}</option>
            </select>
          </label>
          {teamMode && (
            <label className="flex items-center gap-2 text-sm font-semibold">
              <input type="checkbox" className="h-[18px] w-[18px] accent-accent" checked={filter.mine_only} onChange={(e) => setFilter({ ...filter, mine_only: e.target.checked })} />
              {t("filter.mine")}
            </label>
          )}
          <div className="flex justify-between gap-2">
            <button type="button" className="btn" disabled={!n} onClick={() => void save()}>{t("filter.save")}</button>
            <button type="button" className="btn-primary" onClick={() => setOpen(false)}>{t("common.close")}</button>
          </div>
        </div>
      )}
    </div>
  );
}
