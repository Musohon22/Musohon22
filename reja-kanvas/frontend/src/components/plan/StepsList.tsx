"use client";

import { useState } from "react";
import { addStep, deleteStep, reorderSteps, updateStep, useStore, useT } from "@/lib/store";
import { fmtDate, fromLocalInput, toLocalInput } from "@/lib/time";
import type { Person, Step } from "@/lib/types";
import { More, Plus } from "../Icons";

export function StepsList({ planId, steps, editable, people = [] }: { planId: string; steps: Step[]; editable: boolean; people?: Person[] }) {
  const t = useT();
  const [draft, setDraft] = useState("");
  const [dragId, setDragId] = useState<string | null>(null);
  const sorted = [...steps].sort((a, b) => a.position - b.position);
  const ids = sorted.map((s) => s.id);

  const move = (id: string, to: number) => {
    const from = ids.indexOf(id);
    if (from < 0 || to < 0 || to >= ids.length || from === to) return;
    const next = [...ids];
    next.splice(to, 0, next.splice(from, 1)[0]);
    void reorderSteps(planId, next);
  };

  return (
    <div className="flex flex-col gap-1">
      {sorted.map((s, i) => (
        <div
          key={s.id}
          draggable={editable}
          onDragStart={(e) => {
            setDragId(s.id);
            e.dataTransfer.effectAllowed = "move";
          }}
          onDragOver={(e) => editable && dragId && e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (dragId) move(dragId, i);
            setDragId(null);
          }}
          onDragEnd={() => setDragId(null)}
          className={dragId === s.id ? "opacity-40" : ""}
        >
          <StepRow
            planId={planId}
            step={s}
            editable={editable}
            people={people}
            onUp={i > 0 ? () => move(s.id, i - 1) : undefined}
            onDown={i < sorted.length - 1 ? () => move(s.id, i + 1) : undefined}
          />
        </div>
      ))}
      {editable && steps.length < 50 && (
        <form
          className="flex items-center gap-3 rounded-lg px-2.5 py-1"
          onSubmit={(e) => {
            e.preventDefault();
            const text = draft.trim();
            if (!text) return;
            addStep(planId, text.slice(0, 300));
            setDraft("");
          }}
        >
          <Plus size={18} className="flex-none text-ink-muted" />
          <label className="flex-1">
            <span className="sr-only">{t("plan.addStep")}</span>
            <input
              value={draft}
              maxLength={300}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={t("plan.addStep")}
              className="h-10 w-full bg-transparent text-[15px] outline-none placeholder:text-ink-muted"
            />
          </label>
        </form>
      )}
    </div>
  );
}

function StepRow({
  planId, step, editable, people, onUp, onDown,
}: {
  planId: string;
  step: Step;
  editable: boolean;
  people: Person[];
  onUp?: () => void;
  onDown?: () => void;
}) {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const assignee = people.find((p) => p.id === step.assignee_id);
  const [text, setText] = useState(step.text);
  const cancelled = step.status === "cancelled";
  const done = step.status === "done";

  return (
    <div className={`group flex items-center gap-3 rounded-lg px-2.5 py-1.5 ${!done && !cancelled ? "hover:bg-paper-2" : ""}`}>
      {editable && (
        <span aria-hidden="true" title={t("step.drag")} className="-ml-1 cursor-grab select-none text-ink-muted/60 group-hover:text-ink-muted">⋮⋮</span>
      )}
      <input
        type="checkbox"
        aria-label={step.text}
        checked={done}
        disabled={!editable || cancelled}
        onChange={(e) => updateStep(planId, step.id, { status: e.target.checked ? "done" : "todo" })}
        className="h-[18px] w-[18px] flex-none accent-ok"
      />
      {editable && !cancelled ? (
        <input
          value={text}
          maxLength={300}
          aria-label={t("plan.steps")}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => {
            const v = text.trim();
            if (v && v !== step.text) updateStep(planId, step.id, { text: v });
            else setText(step.text);
          }}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          className={`min-w-0 flex-1 bg-transparent text-[15px] outline-none ${done ? "text-ink-muted line-through" : ""}`}
        />
      ) : (
        <span className={`min-w-0 flex-1 text-[15px] ${done || cancelled ? "text-ink-muted line-through" : ""}`}>{step.text}</span>
      )}
      {cancelled && <span className="chip bg-paper-3 text-ink-3">{t("plan.stepNotNeeded")}</span>}
      {step.due_at && !cancelled && (
        <span className={`font-mono text-xs ${!done && new Date(step.due_at) < new Date() ? "font-bold text-warn-strong" : "text-ink-muted"}`}>{fmtDate(step.due_at, user.tz, lang)}</span>
      )}
      {assignee && (
        <span title={assignee.name} className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-[#9FC3FF] text-[11px] font-extrabold text-[#0E2A66]">
          {assignee.name.slice(0, 1).toUpperCase()}
        </span>
      )}
      {editable && (
        <details className="relative">
          <summary aria-label={t("plan.stepActions")} className="flex h-8 w-8 cursor-pointer list-none items-center justify-center rounded-lg text-ink-muted hover:bg-paper-3 [&::-webkit-details-marker]:hidden">
            <More size={16} />
          </summary>
          <div className="absolute right-0 z-20 mt-1 w-64 rounded-xl border border-line bg-surface p-1 shadow-lift">
            <label className="flex flex-col gap-1 px-3 py-2">
              <span className="label">{t("step.due")}</span>
              <input
                type="date"
                className="field h-9"
                value={step.due_at ? toLocalInput(step.due_at, user.tz).slice(0, 10) : ""}
                onChange={(e) => updateStep(planId, step.id, { due_at: e.target.value ? fromLocalInput(`${e.target.value}T18:00`, user.tz) : null })}
              />
            </label>
            {people.length > 1 && (
              <label className="flex flex-col gap-1 px-3 pb-2">
                <span className="label">{t("step.assignee")}</span>
                <select className="field h-9" value={step.assignee_id ?? ""} onChange={(e) => updateStep(planId, step.id, { assignee_id: e.target.value || null })}>
                  <option value="">{t("step.nobody")}</option>
                  {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </label>
            )}
            <div className="flex gap-1 px-2 pb-1">
              <button type="button" className="btn h-9 flex-1 px-2" disabled={!onUp} onClick={onUp}>↑ {t("step.moveUp")}</button>
              <button type="button" className="btn h-9 flex-1 px-2" disabled={!onDown} onClick={onDown}>↓ {t("step.moveDown")}</button>
            </div>
            <button
              type="button"
              className="h-10 w-full rounded-lg px-3 text-left text-sm font-semibold hover:bg-paper-2"
              onClick={(e) => {
                updateStep(planId, step.id, { status: cancelled ? "todo" : "cancelled" });
                (e.currentTarget.closest("details") as HTMLDetailsElement).open = false;
              }}
            >
              {cancelled ? t("plan.stepRestore") : t("plan.stepCancel")}
            </button>
            <button
              type="button"
              className="h-10 w-full rounded-lg px-3 text-left text-sm font-semibold text-warn-strong hover:bg-warn-soft"
              onClick={() => deleteStep(planId, step.id)}
            >
              {t("plan.stepDelete")}
            </button>
          </div>
        </details>
      )}
    </div>
  );
}
