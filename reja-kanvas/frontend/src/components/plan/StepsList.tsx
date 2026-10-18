"use client";

import { useState } from "react";
import { addStep, deleteStep, updateStep, useT } from "@/lib/store";
import type { Step } from "@/lib/types";
import { More, Plus } from "../Icons";

export function StepsList({ planId, steps, editable }: { planId: string; steps: Step[]; editable: boolean }) {
  const t = useT();
  const [draft, setDraft] = useState("");
  const sorted = [...steps].sort((a, b) => a.position - b.position);

  return (
    <div className="flex flex-col gap-1">
      {sorted.map((s) => (
        <StepRow key={s.id} planId={planId} step={s} editable={editable} />
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

function StepRow({ planId, step, editable }: { planId: string; step: Step; editable: boolean }) {
  const t = useT();
  const [text, setText] = useState(step.text);
  const cancelled = step.status === "cancelled";
  const done = step.status === "done";

  return (
    <div className={`group flex items-center gap-3 rounded-lg px-2.5 py-1.5 ${!done && !cancelled ? "hover:bg-[#FFFBEA]" : ""}`}>
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
      {editable && (
        <details className="relative">
          <summary aria-label={t("plan.stepActions")} className="flex h-8 w-8 cursor-pointer list-none items-center justify-center rounded-lg text-ink-muted hover:bg-paper-3 [&::-webkit-details-marker]:hidden">
            <More size={16} />
          </summary>
          <div className="absolute right-0 z-20 mt-1 w-56 rounded-xl border border-line bg-white p-1 shadow-lift">
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
