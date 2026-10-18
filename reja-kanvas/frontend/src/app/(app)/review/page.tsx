"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { toast, updatePlan, useStore, useT } from "@/lib/store";
import { addDays, dayKey, fmtDate, fromLocalInput, toLocalInput } from "@/lib/time";
import type { Plan } from "@/lib/types";
import { Check } from "@/components/Icons";

/** A guided weekly look back and look ahead. */
export default function ReviewPage() {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const planMap = useStore((s) => s.plans);
  const [step, setStep] = useState(0);
  const today = dayKey(new Date(), user.tz);
  const weekAgo = addDays(today, -7);
  const nextWeek = addDays(today, 7);

  const mine = useMemo(() => Object.values(planMap).filter((p) => p.owner_id === user.id), [planMap, user.id]);
  const done = mine.filter((p) => p.status === "done" && p.completed_at && dayKey(p.completed_at, user.tz) >= weekAgo);
  const slipped = mine.filter(
    (p) => (p.status === "active" || p.status === "returned") && p.due_at && dayKey(p.due_at, user.tz) < today,
  ).concat(done.filter((p) => (p.late_minutes ?? 0) > 0));
  const upcoming = mine
    .filter((p) => (p.status === "active" || p.status === "returned") && p.due_at && dayKey(p.due_at, user.tz) >= today && dayKey(p.due_at, user.tz) <= nextWeek)
    .sort((a, b) => a.due_at!.localeCompare(b.due_at!));
  const noDue = mine.filter((p) => p.status === "active" && !p.due_at);

  const sections: { title: string; items: Plan[]; schedule?: boolean }[] = [
    { title: t("review.done"), items: done },
    { title: t("review.slipped"), items: slipped, schedule: true },
    { title: t("review.noDue"), items: noDue, schedule: true },
    { title: t("review.next"), items: upcoming, schedule: true },
  ];
  const current = sections[step];

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-8 sm:px-6">
      <div>
        <h1 className="font-display text-3xl font-extrabold tracking-tight">{t("review.title")}</h1>
        <p className="mt-1 text-ink-3">{t("review.lead")}</p>
      </div>
      <ol className="flex gap-2" aria-label={t("review.title")}>
        {sections.map((s, i) => (
          <li key={s.title} className="flex-1">
            <button
              type="button"
              aria-current={i === step ? "step" : undefined}
              onClick={() => setStep(i)}
              className={`flex w-full flex-col items-start gap-1 rounded-xl border p-3 text-left ${i === step ? "border-accent bg-accent-soft" : "border-line bg-surface"}`}
            >
              <span className="font-mono text-xs text-ink-muted">{i + 1}</span>
              <span className="text-sm font-bold leading-tight">{s.title}</span>
              <span className="text-xs text-ink-muted">{s.items.length}</span>
            </button>
          </li>
        ))}
      </ol>

      <section className="flex flex-col gap-2">
        <h2 className="font-display text-xl font-bold">{current.title}</h2>
        {current.items.length === 0 && <p className="text-ink-muted">{t("review.empty")}</p>}
        <ul className="flex flex-col gap-2">
          {current.items.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface p-3">
              {p.status === "done" && <Check size={16} className="text-ok" />}
              <Link href={`/plan/${p.id}`} className="min-w-0 flex-1 basis-48 truncate font-semibold hover:underline">{p.title}</Link>
              {p.due_at && <span className="font-mono text-xs text-ink-muted">{fmtDate(p.due_at, user.tz, lang)}</span>}
              {current.schedule && p.status !== "done" && (
                <label className="flex items-center gap-1 text-xs">
                  <span className="sr-only">{t("review.schedule")}</span>
                  <input
                    type="date"
                    className="field h-9 w-[150px]"
                    min={today}
                    value={p.due_at && dayKey(p.due_at, user.tz) >= today ? dayKey(p.due_at, user.tz) : ""}
                    onChange={(e) => {
                      if (!e.target.value) return;
                      const time = p.due_at ? toLocalInput(p.due_at, user.tz).slice(11) : "09:00";
                      updatePlan(p.id, { due_at: fromLocalInput(`${e.target.value}T${time}`, user.tz) });
                    }}
                  />
                </label>
              )}
            </li>
          ))}
        </ul>
      </section>

      <div className="flex justify-between gap-2">
        <button type="button" className="btn" disabled={step === 0} onClick={() => setStep(step - 1)}>←</button>
        {step < sections.length - 1 ? (
          <button type="button" className="btn-primary" onClick={() => setStep(step + 1)}>{t("tour.next")} →</button>
        ) : (
          <button type="button" className="btn-primary" onClick={() => toast(t("review.finished"), { tone: "success" })}>{t("review.finish")}</button>
        )}
      </div>
    </main>
  );
}
