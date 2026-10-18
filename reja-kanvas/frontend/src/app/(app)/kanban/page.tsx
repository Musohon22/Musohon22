"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { BoardSwitcher } from "@/components/BoardSwitcher";
import { FilterBar } from "@/components/FilterBar";
import { CARD_BG } from "@/components/canvas/PlanCard";
import { matches } from "@/lib/filter";
import { PRIORITIES, PRIORITY_STYLE } from "@/lib/recurrence";
import { onBoard, updatePlan, useStore, useT } from "@/lib/store";
import { fmtDate, isOverdue } from "@/lib/time";
import type { Plan, PlanStatus, Priority } from "@/lib/types";

type GroupBy = "status" | "priority" | "tag";
const STATUSES: PlanStatus[] = ["active", "returned", "pending_approval", "done"];
const KEY = "reja.kanbanGroup";

export default function KanbanPage() {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const planMap = useStore((s) => s.plans);
  const board = useStore((s) => s.board);
  const boards = useStore((s) => s.boards);
  const filter = useStore((s) => s.filter);
  const [group, setGroupState] = useState<GroupBy>(() => {
    try {
      return (localStorage.getItem(KEY) as GroupBy) || "status";
    } catch {
      return "status";
    }
  });
  const [over, setOver] = useState<string | null>(null);
  const readOnly = boards.find((b) => b.id === board)?.role === "viewer";
  const setGroup = (g: GroupBy) => {
    setGroupState(g);
    try {
      localStorage.setItem(KEY, g);
    } catch {
      /* ignore */
    }
  };

  const plans = useMemo(
    () => Object.values(planMap).filter((p) => onBoard(p, board, user.id) && p.status !== "cancelled" && matches(p, filter, user.tz, user.id)),
    [planMap, board, user.id, user.tz, filter],
  );

  const columns = useMemo(() => {
    if (group === "status") return STATUSES.map((s) => ({ id: s, label: t(`status.${s}`) }));
    if (group === "priority") return PRIORITIES.map((p) => ({ id: p, label: t(`priority.${p}`) }));
    const tags = Array.from(new Set(plans.map((p) => p.tag ?? ""))).sort((a, b) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)));
    return tags.map((tg) => ({ id: tg, label: tg || t("an.untagged") }));
  }, [group, plans, t]);

  const keyOf = (p: Plan) => (group === "status" ? p.status : group === "priority" ? p.priority : p.tag ?? "");
  const movable = group !== "status" && !readOnly;

  function moveTo(plan: Plan, col: string) {
    if (!movable || keyOf(plan) === col) return;
    if (group === "priority") updatePlan(plan.id, { priority: col as Priority });
    else updatePlan(plan.id, { tag: col || null });
  }

  return (
    <main className="flex min-h-0 flex-1 flex-col gap-4 px-4 py-4 sm:px-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-2 font-display text-2xl font-extrabold tracking-tight">{t("kanban.title")}</h1>
        <BoardSwitcher />
        <FilterBar teamMode={!!boards.find((b) => b.id === board)?.team_id} />
        <label className="ml-auto flex items-center gap-2 text-sm">
          <span className="text-ink-muted">{t("kanban.groupBy")}</span>
          <select className="field h-10 w-auto py-0" value={group} onChange={(e) => setGroup(e.target.value as GroupBy)}>
            <option value="status">{t("kanban.byStatus")}</option>
            <option value="priority">{t("kanban.byPriority")}</option>
            <option value="tag">{t("kanban.byTag")}</option>
          </select>
        </label>
      </div>
      <p className="text-sm text-ink-muted">{movable ? t("kanban.dragHint") : group === "status" ? t("kanban.statusReadOnly") : t("board.viewOnly")}</p>
      <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto pb-2">
        {columns.map((col) => {
          const items = plans.filter((p) => keyOf(p) === col.id).sort((a, b) => (a.due_at ?? "9999").localeCompare(b.due_at ?? "9999"));
          return (
            <section
              key={col.id}
              aria-label={col.label}
              onDragOver={(e) => {
                if (!movable) return;
                e.preventDefault();
                setOver(col.id);
              }}
              onDragLeave={() => setOver((o) => (o === col.id ? null : o))}
              onDrop={(e) => {
                e.preventDefault();
                setOver(null);
                const p = planMap[e.dataTransfer.getData("text/plan")];
                if (p) moveTo(p, col.id);
              }}
              className={`flex w-72 flex-none flex-col gap-2 rounded-2xl border p-2 ${over === col.id ? "border-accent bg-accent-soft/50" : "border-line bg-paper-2"}`}
            >
              <h2 className="flex items-center justify-between px-2 pt-1 font-display font-bold">
                {col.label}
                <span className="font-sans text-xs font-semibold text-ink-muted">{items.length}</span>
              </h2>
              <ul className="flex flex-col gap-2 overflow-y-auto">
                {items.map((p) => (
                  <li
                    key={p.id}
                    draggable={movable}
                    onDragStart={(e) => e.dataTransfer.setData("text/plan", p.id)}
                    className={`card-scope rounded-xl p-3 text-ink shadow-card ${CARD_BG[p.color]} ${movable ? "cursor-grab" : ""}`}
                  >
                    <Link href={`/plan/${p.id}`} className="block font-display font-bold leading-snug hover:underline">{p.title}</Link>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
                      {p.priority !== "normal" && <span className={`chip ${PRIORITY_STYLE[p.priority]}`}>{t(`priority.${p.priority}`)}</span>}
                      {p.tag && group !== "tag" && <span className="chip bg-surface/60">{p.tag}</span>}
                      {p.due_at && (
                        <span className={`font-mono ${isOverdue(p) ? "font-bold text-warn-strong" : "text-ink-3"}`}>{fmtDate(p.due_at, user.tz, lang)}</span>
                      )}
                      {p.progress.total > 0 && <span className="font-mono text-ink-3">{p.progress.done}/{p.progress.total}</span>}
                      {p.owner && p.owner_id !== user.id && <span className="text-ink-3">· {p.owner.name}</span>}
                    </div>
                    {movable && (
                      <label className="mt-2 block">
                        <span className="sr-only">{t("kanban.moveTo", { col: "" })}</span>
                        <select
                          className="h-8 w-full rounded-lg border border-black/10 bg-surface/70 px-2 text-xs"
                          value={keyOf(p)}
                          onChange={(e) => moveTo(p, e.target.value)}
                        >
                          {columns.map((c) => <option key={c.id} value={c.id}>{t("kanban.moveTo", { col: c.label })}</option>)}
                        </select>
                      </label>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </main>
  );
}
