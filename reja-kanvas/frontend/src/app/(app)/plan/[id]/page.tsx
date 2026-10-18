"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import {
  deletePlan, loadDetail, loadPlans, online, patchDetail, planAction, storeDetail, toast, updatePlan, useStore, useT,
} from "@/lib/store";
import { fromLocalInput, toLocalInput } from "@/lib/time";
import type { Color, PlanDetail, PlanEvent, Priority } from "@/lib/types";
import { SaveState } from "@/components/SyncBanner";
import { Editor } from "@/components/plan/Editor";
import { StepsList } from "@/components/plan/StepsList";
import { PeoplePicker } from "@/components/plan/PeoplePicker";
import { ConfirmPanel } from "@/components/plan/ConfirmPanel";
import { ShareDialog } from "@/components/plan/ShareDialog";
import { HistoryList } from "@/components/plan/HistoryList";
import { AutoArea, AutoText } from "@/components/plan/AutoSave";
import { ChevronLeft, History, Lock, More, Share, Target } from "@/components/Icons";
import { RecurrencePicker } from "@/components/plan/RecurrencePicker";
import { Dependencies } from "@/components/plan/Dependencies";
import { Comments } from "@/components/plan/Comments";
import { FocusTimer } from "@/components/plan/FocusTimer";
import { PRIORITIES } from "@/lib/recurrence";
import { CARD_BG } from "@/components/canvas/PlanCard";

const COLORS: Color[] = ["yellow", "mint", "lilac", "peach", "sky", "white"];
const REMINDERS = [null, 10, 30, 60, 1440] as const;

export default function PlanPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const t = useT();
  const router = useRouter();
  const user = useStore((s) => s.user)!;
  const plan = useStore((s) => s.details[id]);
  const allPlans = useStore((s) => s.plans);
  const reachable = useStore((s) => s.online && !s.serverDown);
  const [missing, setMissing] = useState<"notfound" | "offline" | null>(null);
  const [events, setEvents] = useState<PlanEvent[]>([]);
  const [shareOpen, setShareOpen] = useState(false);

  const loadEvents = useCallback(() => {
    api.get<{ events: PlanEvent[] }>(`/api/plans/${id}/events`).then((r) => setEvents(r.events)).catch(() => undefined);
  }, [id]);

  const refresh = useCallback(() => {
    loadDetail(id)
      .then((d) => setMissing(d ? null : "offline"))
      .catch((e) => setMissing(e instanceof ApiError && e.status === 404 ? "notfound" : "offline"));
    loadEvents();
  }, [id, loadEvents]);

  useEffect(refresh, [refresh]);

  // Coming from "Done" on the canvas: jump to the confirmation panel.
  useEffect(() => {
    if (plan && window.location.hash === "#confirm") {
      setTimeout(() => document.getElementById("confirm")?.scrollIntoView({ behavior: "smooth", block: "start" }), 100);
    }
  }, [plan?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const tags = useMemo(
    () => Array.from(new Set(Object.values(allPlans).map((p) => p.tag).filter(Boolean) as string[])).slice(0, 20),
    [allPlans],
  );

  if (!plan) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
        <p className="text-lg font-semibold text-ink-3">
          {missing === "notfound" ? t("plan.notFound") : missing === "offline" ? t("plan.offlineDetail") : t("common.loading")}
        </p>
        {missing && <Link href="/canvas" className="btn">{t("plan.back")}</Link>}
      </div>
    );
  }

  const isOwner = plan.my_role === "owner";
  const contentLocked = !isOwner || plan.status === "pending_approval" || plan.status === "done" || plan.status === "cancelled";
  const lockNote =
    plan.status === "done" ? t("plan.lockedDone") : plan.status === "pending_approval" ? t("plan.lockedPending") : plan.status === "cancelled" ? t("plan.lockedCancelled") : null;

  return (
    <div className="flex flex-1 flex-col bg-paper-3">
      <div className="flex flex-wrap items-center gap-3 border-b border-line bg-paper-2 px-4 py-2.5 sm:px-6">
        <Link href={`/canvas?focus=${plan.id}`} className="btn h-10 px-3"><ChevronLeft size={16} />{t("plan.back")}</Link>
        <span className="hidden min-w-0 truncate text-sm text-ink-muted md:block">{plan.title}</span>
        <div className="ml-auto flex items-center gap-2">
          {isOwner && <SaveState planId={plan.id} />}
          {isOwner && (
            <button type="button" className="btn h-10 px-3" disabled={!reachable} onClick={() => setShareOpen(true)}>
              <Share size={16} />{t("plan.share")}
            </button>
          )}
          {isOwner && (
            <details className="relative">
              <summary aria-label={t("plan.more")} className="btn h-10 w-10 cursor-pointer list-none px-0 [&::-webkit-details-marker]:hidden"><More /></summary>
              <div className="absolute right-0 z-30 mt-1 w-60 rounded-xl border border-line bg-surface p-1 shadow-lift">
                {(plan.status === "active" || plan.status === "returned") && (
                  <button
                    type="button"
                    className="h-10 w-full rounded-lg px-3 text-left text-sm font-semibold hover:bg-paper-2"
                    onClick={() => {
                      if (window.confirm(t("plan.cancelConfirm"))) void planAction(plan.id, "cancel").then(loadEvents);
                    }}
                  >
                    {t("plan.cancelPlan")}
                  </button>
                )}
                <button
                  type="button"
                  className="h-10 w-full rounded-lg px-3 text-left text-sm font-semibold hover:bg-paper-2"
                  onClick={async () => {
                    const copy = await online(() => api.post<PlanDetail>(`/api/plans/${plan.id}/duplicate`));
                    if (copy) {
                      storeDetail(copy);
                      toast(t("plan.duplicated"), { tone: "success" });
                      router.push(`/plan/${copy.id}`);
                    }
                  }}
                >
                  {t("plan.duplicate")}
                </button>
                <button
                  type="button"
                  className="h-10 w-full rounded-lg px-3 text-left text-sm font-semibold hover:bg-paper-2"
                  onClick={async () => {
                    const name = window.prompt(t("plan.templateName"), plan.title.slice(0, 60));
                    if (!name?.trim()) return;
                    const ok = await online(() => api.post(`/api/plans/${plan.id}/save-template`, { name: name.trim().slice(0, 60) }));
                    if (ok) toast(t("plan.templateSaved"), { tone: "success" });
                  }}
                >
                  {t("plan.saveTemplate")}
                </button>
                {(plan.status === "done" || plan.status === "cancelled") && (
                  <button
                    type="button"
                    className="h-10 w-full rounded-lg px-3 text-left text-sm font-semibold hover:bg-paper-2"
                    onClick={async () => {
                      const d = await online(() => api.post<PlanDetail>(`/api/plans/${plan.id}/${plan.archived_at ? "unarchive" : "archive"}`));
                      if (d) {
                        storeDetail(d);
                        void loadPlans();
                        if (!plan.archived_at) {
                          toast(t("plan.archived"), { tone: "success" });
                          router.push("/canvas");
                        }
                      }
                    }}
                  >
                    {plan.archived_at ? t("plan.unarchive") : t("plan.archive")}
                  </button>
                )}
                <button
                  type="button"
                  className="h-10 w-full rounded-lg px-3 text-left text-sm font-semibold text-warn-strong hover:bg-warn-soft"
                  onClick={() => {
                    deletePlan(plan.id);
                    router.push("/canvas");
                  }}
                >
                  {t("plan.deletePlan")}
                </button>
              </div>
            </details>
          )}
        </div>
      </div>

      <div className="flex flex-1 flex-wrap">
        <main className="flex min-w-0 flex-[999_1_560px] justify-center px-3 py-6 sm:px-6 sm:py-9">
          <article className="flex w-full max-w-[780px] flex-col gap-5 rounded-md bg-surface px-5 py-8 shadow-paper sm:px-14 sm:py-12">
            {!isOwner && <p className="rounded-lg bg-accent-soft px-3 py-2 text-sm font-semibold text-accent-ink">{t("plan.approverView")}</p>}
            {lockNote && isOwner && (
              <p className="flex items-center gap-2 rounded-lg bg-paper-2 px-3 py-2 text-sm font-semibold text-ink-3">
                <Lock size={15} />
                {lockNote}
              </p>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2">
                <span className="label">{t("plan.tag")}</span>
                <AutoText
                  value={plan.tag ?? ""}
                  maxLength={30}
                  disabled={!isOwner}
                  placeholder={t("plan.tagPlaceholder")}
                  onSave={(v) => updatePlan(plan.id, { tag: v || null })}
                  className="h-9 w-36 rounded-lg border border-line bg-paper-2 px-2.5 text-sm font-bold outline-none focus:border-accent"
                  aria-label={t("plan.tag")}
                  id="tag-input"
                  list="tag-list"
                />
              </label>
              <datalist id="tag-list">{tags.map((tg) => <option key={tg} value={tg} />)}</datalist>
              <fieldset className="flex items-center gap-1.5" disabled={!isOwner}>
                <legend className="sr-only">{t("plan.color")}</legend>
                {COLORS.map((c) => (
                  <label key={c} className="cursor-pointer">
                    <input type="radio" name="color" value={c} checked={plan.color === c} onChange={() => updatePlan(plan.id, { color: c })} className="peer sr-only" />
                    <span className={`block h-7 w-7 rounded-full ${CARD_BG[c]} ring-1 ring-black/10 peer-checked:ring-2 peer-checked:ring-ink peer-checked:ring-offset-2 peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-accent`} />
                    <span className="sr-only">{c}</span>
                  </label>
                ))}
              </fieldset>
            </div>

            <div>
              <label htmlFor="plan-title" className="sr-only">{t("plan.title")}</label>
              <AutoArea
                id="plan-title"
                value={plan.title}
                required
                singleLine
                rows={1}
                maxLength={200}
                disabled={contentLocked}
                onSave={(v) => updatePlan(plan.id, { title: v })}
                className="w-full bg-transparent font-display text-[34px] font-extrabold leading-[1.08] tracking-tight outline-none disabled:text-ink sm:text-[44px]"
              />
              {plan.title.length > 170 && <p className="text-xs text-ink-muted">{t("plan.charsLeft", { n: 200 - plan.title.length })}</p>}
            </div>

            <div className="grid gap-4 border-y border-line-soft py-4 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5">
                <span className="label">{t("plan.due")}</span>
                <span className="flex gap-1.5">
                  <input
                    type="datetime-local"
                    className="field"
                    disabled={contentLocked}
                    value={toLocalInput(plan.due_at, user.tz)}
                    onChange={(e) => updatePlan(plan.id, { due_at: e.target.value ? fromLocalInput(e.target.value, user.tz) : null })}
                  />
                </span>
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="label">{t("plan.reminder")}</span>
                <select
                  className="field"
                  disabled={contentLocked || !plan.due_at}
                  value={plan.remind_minutes ?? ""}
                  onChange={(e) => updatePlan(plan.id, { remind_minutes: e.target.value ? Number(e.target.value) : null })}
                >
                  {REMINDERS.map((m) => (
                    <option key={String(m)} value={m ?? ""}>
                      {m === null ? t("plan.reminderNone") : t(`plan.reminder${m}`)}
                    </option>
                  ))}
                </select>
              </label>
              <PeoplePicker
                label={t("plan.approver")}
                person={plan.approver}
                disabled={contentLocked}
                hint={!plan.approver ? t("plan.selfApprove") : undefined}
                onChange={(p) => {
                  updatePlan(plan.id, p ? { approver_id: p.id } : { approver_id: null, backup_approver_id: null });
                  patchDetail(plan.id, p ? { approver: p } : { approver: null, backup_approver: null });
                }}
              />
              {plan.approver && (
                <PeoplePicker
                  label={t("plan.backupApprover")}
                  person={plan.backup_approver}
                  disabled={contentLocked}
                  hint={t("plan.backupHint")}
                  onChange={(p) => {
                    updatePlan(plan.id, { backup_approver_id: p?.id ?? null });
                    patchDetail(plan.id, { backup_approver: p });
                  }}
                />
              )}
              <label className="flex flex-col gap-1.5">
                <span className="label">{t("plan.priority")}</span>
                <select
                  className="field"
                  disabled={!isOwner}
                  value={plan.priority}
                  onChange={(e) => updatePlan(plan.id, { priority: e.target.value as Priority })}
                >
                  {PRIORITIES.map((p) => <option key={p} value={p}>{t(`priority.${p}`)}</option>)}
                </select>
              </label>
              <RecurrencePicker
                value={plan.recurrence}
                disabled={contentLocked}
                hasDue={!!plan.due_at}
                onChange={(r) => updatePlan(plan.id, { recurrence: r })}
              />
              <label className="flex items-center gap-2.5 text-sm font-semibold sm:col-span-2">
                <input
                  type="checkbox"
                  className="h-[18px] w-[18px] accent-accent"
                  disabled={contentLocked}
                  checked={plan.require_proof}
                  onChange={(e) => updatePlan(plan.id, { require_proof: e.target.checked })}
                />
                {t("plan.requireProof")}
              </label>
            </div>

            <section className="flex gap-3.5 rounded-xl bg-accent-soft/60 p-4">
              <Target size={22} className="mt-1 flex-none text-accent-ink" />
              <div className="flex flex-1 flex-col gap-3">
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-extrabold uppercase tracking-[0.06em] text-accent-ink">{t("plan.goal")}</span>
                  <AutoArea
                    value={plan.goal}
                    maxLength={2000}
                    disabled={contentLocked}
                    placeholder={t("plan.goalPlaceholder")}
                    onSave={(v) => updatePlan(plan.id, { goal: v })}
                    className="w-full bg-transparent text-[15px] leading-relaxed outline-none placeholder:text-ink-muted"
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-extrabold uppercase tracking-[0.06em] text-accent-ink">{t("plan.criteria")}</span>
                  <AutoArea
                    value={plan.done_criteria}
                    maxLength={2000}
                    disabled={contentLocked}
                    placeholder={t("plan.criteriaPlaceholder")}
                    onSave={(v) => updatePlan(plan.id, { done_criteria: v })}
                    className="w-full bg-transparent text-[15px] leading-relaxed outline-none placeholder:text-ink-muted"
                  />
                </label>
              </div>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-2xl font-bold tracking-tight">{t("plan.steps")}</h2>
              <StepsList planId={plan.id} steps={plan.steps} editable={!contentLocked} />
            </section>

            <Dependencies plan={plan} editable={!contentLocked} />

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-2xl font-bold tracking-tight">{t("plan.notes")}</h2>
              <Editor
                html={plan.body_html}
                editable={!contentLocked}
                placeholder={t("plan.notesPlaceholder")}
                onChange={(html) => updatePlan(plan.id, { body_html: html })}
              />
            </section>
          </article>
        </main>

        <aside className="flex w-full flex-col gap-6 border-t border-line bg-paper-2 p-5 sm:p-6 lg:w-[400px] lg:flex-none lg:border-l lg:border-t-0">
          <ConfirmPanel plan={plan} onChanged={refresh} />
          <FocusTimer plan={plan} />
          <Comments planId={plan.id} />
          {events.length > 0 && (
            <section className="flex flex-col gap-3 border-t border-dashed border-line-strong pt-5">
              <h2 className="eyebrow flex items-center gap-2"><History size={14} />{t("plan.history")}</h2>
              <HistoryList events={events} />
            </section>
          )}
        </aside>
      </div>

      {isOwner && <ShareDialog planId={plan.id} open={shareOpen} onClose={() => setShareOpen(false)} />}
    </div>
  );
}
