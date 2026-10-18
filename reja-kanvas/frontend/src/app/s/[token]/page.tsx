"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { errorText, toast, useStore, useT } from "@/lib/store";
import { browserTimeZone, fmtDateTime } from "@/lib/time";
import type { SharedPlan } from "@/lib/types";
import { Editor } from "@/components/plan/Editor";
import { Check, Logo } from "@/components/Icons";

/** Public page for a share link: read-only, or limited editing for an "edit" link. */
export default function SharedPage({ params }: { params: { token: string } }) {
  const t = useT();
  const lang = useStore((s) => s.lang);
  const [plan, setPlan] = useState<SharedPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const version = useRef(1);
  const tz = browserTimeZone();
  const path = `/api/shared/${params.token}`;

  const load = useCallback(() => {
    api
      .get<SharedPlan>(path, { auth: false })
      .then((p) => {
        setPlan(p);
        setTitle(p.title);
        version.current = p.version;
      })
      .catch((e) => setError(e instanceof ApiError ? e.code : "network"));
  }, [path]);

  useEffect(load, [load]);

  async function save(changes: { title?: string; body_html?: string }) {
    try {
      const p = await api.patch<SharedPlan>(path, { base_version: version.current, ...changes }, { auth: false });
      version.current = p.version;
      setPlan(p);
    } catch (e) {
      if (e instanceof ApiError && e.code === "conflict") {
        toast(t("shared.conflict"), { tone: "error" });
        load();
      } else toast(errorText(e), { tone: "error" });
    }
  }

  if (error) {
    const heading = error === "share_expired" ? t("shared.expiredTitle") : error === "share_revoked" ? t("shared.revokedTitle") : error === "network" ? t("err.network") : t("shared.notFound");
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center gap-3 p-8 text-center">
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-ink text-paper"><Logo size={24} /></span>
        <h1 className="font-display text-3xl font-extrabold">{heading}</h1>
        {error !== "network" && <p className="text-ink-3">{t("shared.lead")}</p>}
      </main>
    );
  }
  if (!plan) return <main className="flex min-h-dvh items-center justify-center text-ink-muted">{t("common.loading")}</main>;

  const editable = plan.share_role === "edit" && plan.status !== "done" && plan.status !== "pending_approval";

  return (
    <main className="min-h-dvh bg-paper-3 px-3 py-8 sm:px-6">
      <div className="mx-auto mb-4 flex max-w-[780px] flex-wrap items-center gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-ink text-paper"><Logo size={20} /></span>
        <span className="text-sm text-ink-3">{t("shared.from", { name: plan.owner?.name ?? "—" })}</span>
        <span className={`chip ml-auto ${editable ? "bg-accent-soft text-accent-ink" : "bg-surface text-ink-3"}`}>
          {editable ? t("shared.canEdit") : t("shared.viewOnly")}
        </span>
      </div>
      <article className="mx-auto flex max-w-[780px] flex-col gap-5 rounded-md bg-surface px-5 py-8 shadow-paper sm:px-14 sm:py-12">
        {plan.status === "done" && (
          <div className="flex -rotate-3 items-center gap-1.5 self-start rounded-lg border-[2.5px] border-ok px-2.5 py-1 font-display text-sm font-extrabold tracking-[0.08em] text-ok">
            <Check size={15} />{t("card.stampDone")}
          </div>
        )}
        {editable ? (
          <label>
            <span className="sr-only">{t("plan.title")}</span>
            <input
              value={title}
              maxLength={200}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={() => title.trim() && title.trim() !== plan.title && void save({ title: title.trim() })}
              className="w-full bg-transparent font-display text-4xl font-extrabold tracking-tight outline-none"
            />
          </label>
        ) : (
          <h1 className="font-display text-4xl font-extrabold tracking-tight">{plan.title}</h1>
        )}
        {plan.due_at && <p className="text-sm text-ink-3"><b>{t("plan.due")}:</b> {fmtDateTime(plan.due_at, tz, lang)}</p>}
        {(plan.goal || plan.done_criteria) && (
          <div className="flex flex-col gap-2 rounded-xl bg-accent-soft/60 p-4 text-[15px]">
            {plan.goal && <p><b>{t("plan.goal")}:</b> {plan.goal}</p>}
            {plan.done_criteria && <p><b>{t("plan.criteria")}:</b> {plan.done_criteria}</p>}
          </div>
        )}
        {plan.steps.length > 0 && (
          <section>
            <h2 className="mb-2 font-display text-2xl font-bold">{t("plan.steps")}</h2>
            <ul className="flex flex-col gap-1.5">
              {plan.steps.map((s) => (
                <li key={s.id} className={`flex items-center gap-2.5 ${s.status !== "todo" ? "text-ink-muted line-through" : ""}`}>
                  <span aria-hidden="true" className={`flex h-[18px] w-[18px] items-center justify-center rounded border-2 ${s.status === "done" ? "border-ok bg-ok text-white" : "border-line-strong"}`}>
                    {s.status === "done" && <Check size={12} />}
                  </span>
                  {s.text}
                </li>
              ))}
            </ul>
          </section>
        )}
        <section>
          <h2 className="mb-2 font-display text-2xl font-bold">{t("plan.notes")}</h2>
          <Editor html={plan.body_html} editable={editable} placeholder={t("plan.notesPlaceholder")} onChange={(html) => void save({ body_html: html })} />
        </section>
      </article>
    </main>
  );
}
