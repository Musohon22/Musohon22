"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { loadDetail, useStore, useT } from "@/lib/store";
import { durationParts, fmtDateTime } from "@/lib/time";
import type { PlanDetail } from "@/lib/types";
import { ChevronLeft, Logo } from "@/components/Icons";

/** A printable certificate of completion: what was done, by whom, approved by whom, with signatures. */
export default function ActPage({ params }: { params: { id: string } }) {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const cached = useStore((s) => s.details[params.id]);
  const [plan, setPlan] = useState<PlanDetail | null>(cached ?? null);

  useEffect(() => {
    loadDetail(params.id).then((d) => d && setPlan(d)).catch(() => undefined);
  }, [params.id]);

  if (!plan) return <p className="p-8 text-ink-muted">{t("common.loading")}</p>;
  const when = (iso: string | null) => (iso ? fmtDateTime(iso, user.tz, lang) : "—");
  const late = plan.late_minutes ? durationParts(plan.late_minutes) : null;
  const sigLabel = (role: string) => (role === "owner" ? t("sig.ownerRole") : t("sig.stageRole", { n: role.replace("stage", "") }));

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-6 print:max-w-none print:p-0">
      <div className="mb-4 flex flex-wrap items-center gap-2 print:hidden">
        <Link href={`/plan/${plan.id}`} className="btn h-10 px-3"><ChevronLeft size={16} />{plan.title}</Link>
        <button type="button" className="btn-primary ml-auto" onClick={() => window.print()} disabled={plan.status !== "done"}>{t("act.print")}</button>
      </div>
      {plan.status !== "done" && <p className="mb-4 rounded-xl bg-warn-soft p-4 text-warn-ink print:hidden">{t("act.notDone")}</p>}
      <article className="card-scope flex flex-col gap-6 rounded-md bg-white p-8 text-ink shadow-paper print:shadow-none sm:p-12">
        <header className="flex items-start justify-between gap-4 border-b-2 border-ink pb-4">
          <div>
            <div className="flex items-center gap-2 text-sm font-bold"><Logo size={18} />Reja</div>
            <h1 className="mt-2 font-display text-3xl font-extrabold">{t("act.title")}</h1>
          </div>
          <div className="text-right text-xs text-ink-muted">
            <div>{t("act.id")}</div>
            <div className="font-mono">{plan.id.slice(0, 8).toUpperCase()}</div>
          </div>
        </header>
        <dl className="grid grid-cols-[minmax(0,10rem)_1fr] gap-x-6 gap-y-3 text-sm">
          <dt className="font-semibold text-ink-muted">{t("act.plan")}</dt><dd className="font-bold">{plan.title}</dd>
          <dt className="font-semibold text-ink-muted">{t("act.owner")}</dt><dd>{plan.owner?.name ?? "—"}</dd>
          <dt className="font-semibold text-ink-muted">{t("act.due")}</dt><dd>{when(plan.due_at)}</dd>
          <dt className="font-semibold text-ink-muted">{t("act.completed")}</dt>
          <dd>{when(plan.completed_at)}{late ? ` · ${t("confirm.lateBy", { d: t(`common.${late.unit}`, { n: late.n }) })}` : plan.due_at ? ` · ${t("confirm.onTime")}` : ""}</dd>
          {plan.goal && (<><dt className="font-semibold text-ink-muted">{t("plan.goal")}</dt><dd>{plan.goal}</dd></>)}
          {plan.done_criteria && (<><dt className="font-semibold text-ink-muted">{t("plan.criteria")}</dt><dd>{plan.done_criteria}</dd></>)}
          {(plan.final_note || plan.rating) && (
            <><dt className="font-semibold text-ink-muted">{t("act.result")}</dt><dd>{plan.rating ? `${t(`rating.${plan.rating}`)}. ` : ""}{plan.final_note}</dd></>
          )}
        </dl>
        {plan.steps.some((s) => s.status === "done") && (
          <section>
            <h2 className="mb-2 font-display text-lg font-bold">{t("act.steps")}</h2>
            <ol className="list-decimal pl-5 text-sm">
              {plan.steps.filter((s) => s.status === "done").map((s) => <li key={s.id}>{s.text}</li>)}
            </ol>
          </section>
        )}
        <section>
          <h2 className="mb-3 font-display text-lg font-bold">{t("act.approvals")}</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {(plan.signatures ?? []).map((s, i) => (
              <figure key={i} className="flex flex-col gap-1 border-t border-ink pt-2">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={s.image} alt={`${t("sig.title")}: ${s.user_name ?? ""}`} className="h-20 object-contain object-left" />
                <figcaption className="text-xs">
                  <b>{s.user_name ?? "—"}</b> · {sigLabel(s.role)}
                  <div className="text-ink-muted">{when(s.signed_at)}</div>
                </figcaption>
              </figure>
            ))}
            {plan.approved_by && !(plan.signatures ?? []).some((s) => s.role !== "owner") && (
              <div className="border-t border-ink pt-2 text-xs"><b>{plan.approved_by.name}</b> · {when(plan.approved_at)}</div>
            )}
          </div>
        </section>
      </article>
    </main>
  );
}
