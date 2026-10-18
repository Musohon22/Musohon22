"use client";

import { memo, useEffect, useRef, useState } from "react";
import { CARD_W } from "@/lib/canvas";
import { fmtDate, fmtTime, isOverdue, zoneOf } from "@/lib/time";
import type { Lang, Plan } from "@/lib/types";
import { useT } from "@/lib/store";
import { Alert, Check, Clock, Lock, Open, Trash } from "../Icons";

export const CARD_BG: Record<Plan["color"], string> = {
  yellow: "bg-card-yellow",
  mint: "bg-card-mint",
  lilac: "bg-card-lilac",
  peach: "bg-card-peach",
  sky: "bg-card-sky",
  white: "bg-card-white border border-line",
};

const TAG_INK: Record<Plan["color"], string> = {
  yellow: "text-[#6B4E00]",
  mint: "text-[#155C33]",
  lilac: "text-[#3E2A9E]",
  peach: "text-[#8A3B0A]",
  sky: "text-[#1E44D6]",
  white: "text-ink-2",
};

interface Props {
  plan: Plan;
  tz: string;
  lang: Lang;
  selected: boolean;
  dragging: boolean;
  pulse: boolean;
  lowDetail: boolean;
  editing: boolean;
  onPointerDown: (e: React.PointerEvent, plan: Plan) => void;
  onKeyDown: (e: React.KeyboardEvent, plan: Plan) => void;
  onOpen: (plan: Plan) => void;
  onQuickDone: (plan: Plan) => void;
  onDelete: (plan: Plan) => void;
  onRename: (plan: Plan, title: string | null) => void;
  measure: (id: string, el: HTMLElement | null) => void;
}

function PlanCardInner(props: Props) {
  const { plan, tz, lang, selected, dragging, pulse, lowDetail, editing } = props;
  const t = useT();
  const overdue = isOverdue(plan);
  const finished = plan.status === "done";
  const cancelled = plan.status === "cancelled";
  const ink = TAG_INK[plan.color];
  const today = zoneOf(plan, tz) === "today";
  const pct = plan.progress.total ? Math.round((plan.progress.done / plan.progress.total) * 100) : 0;

  return (
    <article
      ref={(el) => props.measure(plan.id, el)}
      tabIndex={0}
      aria-label={t("card.label", { title: plan.title })}
      data-plan={plan.id}
      onPointerDown={(e) => props.onPointerDown(e, plan)}
      onDoubleClick={() => props.onOpen(plan)}
      onKeyDown={(e) => props.onKeyDown(e, plan)}
      style={{
        position: "absolute",
        left: plan.x,
        top: plan.y,
        width: CARD_W,
        transform: dragging ? "rotate(-2.5deg) scale(1.02)" : undefined,
        zIndex: dragging ? 30 : selected ? 20 : undefined,
        touchAction: "none",
      }}
      className={`group select-none rounded-2xl p-4 outline-none transition-shadow ${CARD_BG[plan.color]} ${
        dragging ? "cursor-grabbing shadow-lift" : "cursor-grab shadow-card"
      } ${selected ? "ring-2 ring-accent ring-offset-2 ring-offset-paper" : "focus-visible:ring-2 focus-visible:ring-accent"} ${
        pulse ? "animate-pulsering" : ""
      } ${cancelled ? "opacity-60" : ""}`}
    >
      {lowDetail ? (
        <div className={`font-display text-[28px] font-bold leading-tight ${finished || cancelled ? "line-through" : ""}`}>{plan.title}</div>
      ) : (
        <div className="flex flex-col gap-2.5">
          <div className="flex items-center justify-between gap-2">
            {plan.tag ? <span className={`chip bg-white/60 ${ink}`}>{plan.tag}</span> : <span />}
            {plan.due_at && (
              <span className={`flex items-center gap-1 font-mono text-xs ${overdue ? "font-bold text-warn-strong" : ink}`}>
                {overdue ? <Alert size={13} /> : <Clock size={13} />}
                {today ? fmtTime(plan.due_at, tz, lang) : `${fmtDate(plan.due_at, tz, lang)} ${fmtTime(plan.due_at, tz, lang)}`}
              </span>
            )}
          </div>

          {editing ? (
            <TitleInput plan={plan} onDone={(v) => props.onRename(plan, v)} label={t("card.rename")} />
          ) : (
            <h3
              className={`line-clamp-2 break-words font-display text-xl font-bold leading-tight tracking-tight ${
                finished || cancelled ? "text-ink-3 line-through decoration-2" : ""
              }`}
              title={plan.title}
            >
              {plan.title}
            </h3>
          )}

          {plan.progress.total > 0 && !finished && (
            <div className="flex items-center gap-2.5">
              <div className="h-1.5 flex-1 rounded-full bg-black/10">
                <div className="h-1.5 rounded-full bg-ink transition-[width]" style={{ width: `${pct}%` }} />
              </div>
              <span className={`font-mono text-xs ${ink}`}>{plan.progress.done}/{plan.progress.total}</span>
            </div>
          )}

          {overdue && <div className="text-xs font-bold text-warn-strong">{t("card.overdue")}</div>}
          {plan.status === "pending_approval" && (
            <div className="flex items-center gap-1.5 text-xs font-bold text-accent-ink"><Lock size={13} />{t("card.pending")}</div>
          )}
          {plan.status === "returned" && (
            <div className="rounded-lg bg-warn-soft px-2 py-1.5 text-xs text-warn-ink">
              <b>{t("card.returned")}</b>
              {plan.return_reason && <span className="line-clamp-1">{plan.return_reason}</span>}
            </div>
          )}
          {cancelled && <div className="text-xs font-bold text-ink-3">{t("card.cancelled")}</div>}

          {selected && !editing && (
            <div className="flex gap-1.5 pt-1" onPointerDown={(e) => e.stopPropagation()}>
              <button type="button" className="btn h-9 flex-1 bg-white/80 px-2" onClick={() => props.onOpen(plan)}>
                <Open size={15} />{t("card.open")}
              </button>
              {(plan.status === "active" || plan.status === "returned") && (
                <button type="button" className="btn h-9 flex-1 bg-white/80 px-2" onClick={() => props.onQuickDone(plan)}>
                  <Check size={15} />{t("card.done")}
                </button>
              )}
              <button type="button" aria-label={t("card.delete")} className="btn h-9 w-9 bg-white/80 px-0" onClick={() => props.onDelete(plan)}>
                <Trash size={15} />
              </button>
            </div>
          )}
        </div>
      )}

      {finished && (
        <div
          aria-hidden="true"
          className={`pointer-events-none absolute right-3 top-3 flex animate-stamp items-center gap-1 rounded-lg border-[2.5px] px-2 py-1 font-display text-[13px] font-extrabold tracking-[0.08em] ${
            plan.late_minutes ? "border-warn-strong bg-card-peach/90 text-warn-strong" : "border-ok bg-card-mint/90 text-ok"
          }`}
          style={{ transform: "rotate(-12deg)" }}
        >
          <Check size={14} />
          {plan.late_minutes ? t("card.stampLate") : t("card.stampDone")}
        </div>
      )}
    </article>
  );
}

function TitleInput({ plan, onDone, label }: { plan: Plan; onDone: (v: string | null) => void; label: string }) {
  const [value, setValue] = useState(plan.title);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);
  return (
    <textarea
      ref={ref}
      aria-label={label}
      value={value}
      maxLength={200}
      rows={2}
      onPointerDown={(e) => e.stopPropagation()}
      onChange={(e) => setValue(e.target.value.replace(/\n/g, " "))}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Enter") {
          e.preventDefault();
          onDone(value.trim() || null);
        }
        if (e.key === "Escape") onDone(null);
      }}
      onBlur={() => onDone(value.trim() || null)}
      className="w-full resize-none rounded-lg border-0 bg-white/70 p-1.5 font-display text-xl font-bold leading-tight outline-none ring-2 ring-accent"
    />
  );
}

export const PlanCard = memo(PlanCardInner);
