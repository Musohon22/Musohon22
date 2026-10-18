"use client";

import { useEffect, useRef, useState } from "react";
import { api, openAttachment } from "@/lib/api";
import { submitWithUndo } from "@/lib/actions";
import { online, planAction, setAttachments, settle, toast, toastError, useStore, useT } from "@/lib/store";
import { durationParts, fmtDateTime } from "@/lib/time";
import type { Attachment, PlanDetail, Rating } from "@/lib/types";
import { Check, Lock, Upload, X } from "../Icons";
import { SignaturePad } from "./SignaturePad";

const MAX_BYTES = 20 * 1024 * 1024;
const ALLOWED = ["pdf", "jpg", "jpeg", "png", "webp"];
const RATINGS: Rating[] = ["excellent", "good", "partial"];

export function ConfirmPanel({ plan, onChanged }: { plan: PlanDetail; onChanged: () => void }) {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const reachable = useStore((s) => s.online && !s.serverDown);
  const [note, setNote] = useState(plan.final_note ?? "");
  const [rating, setRating] = useState<Rating | null>(plan.rating);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [reopenNote, setReopenNote] = useState("");
  const [reopening, setReopening] = useState(false);
  const [signature, setSignature] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setNote(plan.final_note ?? "");
    setRating(plan.rating);
  }, [plan.id, plan.final_note, plan.rating]);

  const isOwner = plan.my_role === "owner" || plan.my_role === "team";
  const { done, total } = plan.progress;
  const stepsOk = done >= total;
  const proofOk = !plan.require_proof || plan.attachments.some((a) => !a.inline);
  const planMap = useStore((s) => s.plans);
  // Blockers still open, using fresh local status where we have it.
  const waiting = (plan.open_blockers ?? []).filter((b) => {
    const local = planMap[b.id];
    return !local || (local.status !== "done" && local.status !== "cancelled");
  });
  const childrenOpen = (plan.children ?? []).some((c) => c.status !== "done" && c.status !== "cancelled");
  const ready = stepsOk && proofOk && waiting.length === 0 && !childrenOpen;
  const proofFiles = plan.attachments.filter((a) => !a.inline);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File) {
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!ALLOWED.includes(ext)) return toast(t("err.file_type_not_allowed"), { tone: "error" });
    if (file.size > MAX_BYTES) return toast(t("err.file_too_large"), { tone: "error" });
    if (file.size === 0) return toast(t("err.file_empty"), { tone: "error" });
    if (!(await settle(plan.id))) return;
    setUploading(true);
    const att = await online(() => api.upload<Attachment>(`/api/plans/${plan.id}/attachments`, file));
    setUploading(false);
    if (att) {
      setAttachments(plan.id, [...plan.attachments, att]);
      onChanged();
    }
  }

  async function removeFile(att: Attachment) {
    if (!reachable) return toast(t("err.offline_action"), { tone: "error" });
    try {
      await api.del(`/api/attachments/${att.id}`);
      setAttachments(plan.id, plan.attachments.filter((a) => a.id !== att.id));
      onChanged();
    } catch (e) {
      toastError(e);
    }
  }

  const fileList = (removable: boolean) =>
    proofFiles.length > 0 && (
      <ul className="flex flex-col gap-1.5">
        {proofFiles.map((a) => (
          <li key={a.id} className="flex items-center gap-2 rounded-xl bg-paper px-2.5 py-2">
            <span aria-hidden="true" className={`flex h-9 w-8 flex-none items-end justify-center rounded-md pb-1 text-[9px] font-extrabold text-white ${a.mime === "application/pdf" ? "bg-warn" : "bg-accent"}`}>
              {a.filename.split(".").pop()?.toUpperCase()}
            </span>
            <button
              type="button"
              className="min-w-0 flex-1 text-left"
              onClick={() => openAttachment(a.id, a.filename).catch(toastError)}
            >
              <span className="block truncate text-sm font-bold underline-offset-2 hover:underline">{a.filename}</span>
              <span className="text-xs text-ink-muted">{(a.size / 1024 / 1024).toFixed(1)} MB</span>
            </button>
            {removable && (
              <button type="button" aria-label={t("confirm.removeFile", { name: a.filename })} className="btn-icon h-9 w-9" onClick={() => void removeFile(a)}>
                <X size={16} />
              </button>
            )}
          </li>
        ))}
      </ul>
    );

  const late = plan.late_minutes ? durationParts(plan.late_minutes) : null;
  const lateText = late ? t(`common.${late.unit}`, { n: late.n }) : "";

  return (
    <section id="confirm" aria-labelledby="confirm-title" className="flex flex-col gap-4 scroll-mt-4">
      <div>
        <h2 id="confirm-title" className="font-display text-[22px] font-extrabold tracking-tight">{t("confirm.title")}</h2>
        <p className="mt-0.5 text-sm text-ink-muted">{t("confirm.lead")}</p>
      </div>

      {/* ---- done ---- */}
      {plan.status === "done" && (
        <div className={`card-scope flex flex-col gap-3 rounded-2xl p-4 text-ink ${plan.late_minutes ? "bg-card-peach" : "bg-card-mint"}`}>
          <div className="flex items-center gap-4">
            <div
              aria-hidden="true"
              className={`flex h-[72px] w-[72px] flex-none animate-stamp flex-col items-center justify-center rounded-full border-[3px] font-display text-[9px] font-extrabold tracking-[0.1em] ${plan.late_minutes ? "border-warn-strong text-warn-strong" : "border-ok text-ok"}`}
            >
              <Check size={24} />
              {t("card.stampDone")}
            </div>
            <div className="min-w-0">
              <div className="font-extrabold text-ok-ink">{t("confirm.doneTitle")} · {fmtDateTime(plan.completed_at!, user.tz, lang)}</div>
              <div className="text-sm text-[#1F5A3A]">{plan.approved_by ? t("confirm.by", { name: plan.approved_by.name }) : t("confirm.selfDone")}</div>
              <div className={`text-sm ${plan.late_minutes ? "font-bold text-warn-strong" : "text-[#1F5A3A]"}`}>
                {plan.late_minutes ? t("confirm.lateBy", { d: lateText }) : plan.due_at ? t("confirm.onTime") : null}
              </div>
            </div>
          </div>
          {plan.rating && <div className="chip self-start bg-surface/70 text-ink">{t(`rating.${plan.rating}`)}</div>}
          <a href={`/plan/${plan.id}/act`} className="self-start text-sm font-bold underline underline-offset-2">{t("plan.act")}</a>
          {plan.final_note && <p className="text-sm text-ink-2">{plan.final_note}</p>}
          {fileList(false)}
          {(isOwner || plan.my_role === "approver" || plan.my_role === "backup") &&
            (reopening ? (
              <form
                className="flex flex-col gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  void run(() => planAction(plan.id, "reopen", { reason: "reopen", note: reopenNote }));
                  setReopening(false);
                }}
              >
                <label className="flex flex-col gap-1">
                  <span className="label">{t("confirm.reopenNote")}</span>
                  <input className="field" value={reopenNote} maxLength={1000} onChange={(e) => setReopenNote(e.target.value)} />
                </label>
                <div className="flex gap-2">
                  <button className="btn-dark flex-1" disabled={busy}>{t("confirm.reopen")}</button>
                  <button type="button" className="btn" onClick={() => setReopening(false)}>{t("common.cancel")}</button>
                </div>
              </form>
            ) : (
              <button type="button" className="btn self-start bg-surface/70" onClick={() => setReopening(true)}>{t("confirm.reopen")}</button>
            ))}
        </div>
      )}

      {/* ---- cancelled ---- */}
      {plan.status === "cancelled" && (
        <div className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-4">
          <div className="font-bold">{t("confirm.cancelledTitle")}</div>
          {isOwner && (
            <button type="button" className="btn self-start" disabled={busy} onClick={() => void run(() => planAction(plan.id, "reopen", { reason: "reopen" }))}>
              {t("confirm.restore")}
            </button>
          )}
        </div>
      )}

      {/* ---- waiting for approval ---- */}
      {plan.status === "pending_approval" && !plan.can_decide && (
        <div className="flex flex-col gap-3 rounded-2xl bg-accent-soft p-4">
          <div className="flex -rotate-2 items-center gap-2 self-start rounded-lg border-[2.5px] border-accent-ink px-2 py-1 font-display text-xs font-extrabold tracking-[0.08em] text-accent-ink">
            <Lock size={14} />
            {t("confirm.pendingStamp")}
          </div>
          <div className="font-bold">{t("confirm.waiting", { name: (plan.escalated_at && plan.backup_approver ? plan.backup_approver.name : plan.approver?.name) ?? "—" })}</div>
          {plan.submitted_at && <div className="text-sm text-ink-3">{t("confirm.sentAt", { time: fmtDateTime(plan.submitted_at, user.tz, lang) })}</div>}
          {plan.escalated_at && <div className="rounded-lg bg-surface/70 px-3 py-2 text-sm text-warn-ink">{t("confirm.escalated")}</div>}
          {fileList(false)}
          {isOwner && (
            <button type="button" className="btn self-start" disabled={busy} onClick={() => void run(() => planAction(plan.id, "reopen", { reason: "withdraw" }))}>
              {t("confirm.withdraw")}
            </button>
          )}
        </div>
      )}

      {/* ---- approver decides ---- */}
      {plan.status === "pending_approval" && plan.can_decide && (
        <div className="flex flex-col gap-3 rounded-2xl bg-ink p-5 text-paper">
          <div className="text-xs font-bold uppercase tracking-[0.08em] text-paper/75">{t("confirm.decideTitle")}</div>
          <div className="font-display text-lg font-bold">{t("confirm.decideLead", { name: plan.owner?.name ?? "—" })}</div>
          {plan.submitted_at && <div className="text-sm text-paper/75">{t("confirm.sentAt", { time: fmtDateTime(plan.submitted_at, user.tz, lang) })}</div>}
          <div className="text-sm text-paper/75">{t("confirm.step1")}: {done}/{total}</div>
          {plan.final_note && <p className="rounded-lg bg-surface/10 p-3 text-sm">{plan.final_note}</p>}
          {plan.attachments.length > 0 && <div className="rounded-xl bg-paper p-1 text-ink">{fileList(false)}</div>}
          {(plan.chain?.length ?? 0) > 1 && (
            <div className="text-sm text-paper/75">{t("plan.stageN", { n: (plan.approval_stage ?? 0) + 1 })} / {plan.chain!.length}</div>
          )}
          {!rejecting && (
            <div className="rounded-xl bg-paper p-2 text-ink">
              <SignaturePad label={t("sig.optional")} onChange={setSignature} />
            </div>
          )}
          {rejecting ? (
            <form
              className="flex flex-col gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void run(() => planAction(plan.id, "reject", { reason: reason.trim() }));
              }}
            >
              <label className="flex flex-col gap-1">
                <span className="text-sm font-bold">{t("confirm.rejectReason")}</span>
                <textarea
                  className="field h-auto py-2 text-ink"
                  rows={3}
                  minLength={3}
                  maxLength={1000}
                  required
                  value={reason}
                  placeholder={t("confirm.rejectPlaceholder")}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
              <div className="flex gap-2">
                <button className="inline-flex h-11 flex-1 items-center justify-center rounded-xl bg-warn font-bold text-white disabled:opacity-50" disabled={busy || reason.trim().length < 3}>
                  {t("confirm.reject")}
                </button>
                <button type="button" className="h-11 rounded-xl px-4 font-bold text-paper/80" onClick={() => setRejecting(false)}>{t("common.cancel")}</button>
              </div>
            </form>
          ) : (
            <div className="flex gap-2">
              <button type="button" className="inline-flex h-12 flex-1 items-center justify-center gap-2 rounded-xl bg-paper font-extrabold text-ink disabled:opacity-50" disabled={busy || !reachable} onClick={() => void run(() => planAction(plan.id, "approve", signature ? { signature } : {}))}>
                <Check size={18} />
                {t("confirm.approve")}
              </button>
              <button type="button" className="h-12 rounded-xl border border-white/30 px-4 font-bold" onClick={() => setRejecting(true)}>{t("confirm.reject")}</button>
            </div>
          )}
        </div>
      )}

      {/* ---- owner completes ---- */}
      {isOwner && (plan.status === "active" || plan.status === "returned") && (
        <>
          {plan.status === "returned" && (
            <div role="alert" className="rounded-2xl border border-warn/40 bg-warn-soft p-4">
              <div className="font-extrabold text-warn-ink">{t("confirm.returnedTitle")}</div>
              {plan.return_reason && <p className="mt-1 text-sm text-warn-ink">«{plan.return_reason}»</p>}
              <p className="mt-1 text-sm text-warn-ink">{t("confirm.returnedLead")}</p>
            </div>
          )}
          <ol className="flex flex-col gap-3">
            <Step n={1} ok={stepsOk} title={t("confirm.step1")}>
              {total === 0 ? (
                <span className="text-xs text-ink-muted">{t("confirm.step1None")}</span>
              ) : (
                <>
                  <div className="flex items-center gap-2.5">
                    <div className="h-1.5 flex-1 rounded-full bg-line-soft">
                      <div className={`h-1.5 rounded-full ${stepsOk ? "bg-ok" : "bg-warn"}`} style={{ width: `${(done / total) * 100}%` }} />
                    </div>
                    <span className="font-mono text-xs">{done}/{total}</span>
                  </div>
                  {!stepsOk && <span className="text-xs text-ink-muted">{t("confirm.left", { n: total - done })}</span>}
                </>
              )}
            </Step>
            <Step n={2} ok={plan.attachments.length > 0} title={t("confirm.step2")} badge={plan.require_proof ? t("confirm.required") : t("confirm.optional")}>
              {fileList(true)}
              <input
                ref={fileInput}
                type="file"
                accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp"
                className="sr-only"
                tabIndex={-1}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) void upload(f);
                }}
              />
              {plan.attachments.length < 10 && (
                <button type="button" className="btn h-10 self-start" disabled={uploading || !reachable} onClick={() => fileInput.current?.click()}>
                  <Upload size={16} />
                  {uploading ? t("confirm.uploading") : t("confirm.upload")}
                </button>
              )}
              <span className="text-xs text-ink-muted">{t("confirm.uploadHint")}</span>
            </Step>
            <Step n={3} ok={!!note.trim()} title={t("confirm.step3")} badge={t("confirm.optional")}>
              <SignaturePad label={t("sig.optional")} onChange={setSignature} />
              <label>
                <span className="sr-only">{t("confirm.step3")}</span>
                <textarea
                  rows={2}
                  maxLength={2000}
                  value={note}
                  placeholder={t("confirm.notePlaceholder")}
                  onChange={(e) => setNote(e.target.value)}
                  className="field h-auto resize-none py-2.5"
                />
              </label>
              <div role="group" aria-label={t("confirm.rating")} className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs font-semibold text-ink-muted">{t("confirm.rating")}</span>
                {RATINGS.map((r) => (
                  <button
                    key={r}
                    type="button"
                    aria-pressed={rating === r}
                    onClick={() => setRating(rating === r ? null : r)}
                    className={`h-9 rounded-lg border-[1.5px] px-3 text-sm font-bold ${rating === r ? "border-ink bg-ink text-white" : "border-line-strong"}`}
                  >
                    {t(`rating.${r}`)}
                  </button>
                ))}
              </div>
            </Step>
          </ol>

          <div className="flex flex-col gap-2">
            <button
              type="button"
              disabled={!ready || busy || !reachable}
              onClick={() => void run(() => submitWithUndo(plan.id, { final_note: note.trim(), rating, ...(signature ? { signature } : {}) }))}
              className="btn-primary h-14 text-base"
            >
              {ready ? <Check size={18} /> : <Lock size={18} />}
              {plan.approver ? t("confirm.submitToApprover") : t("confirm.submit")}
            </button>
            <p className="text-center text-xs text-ink-3">
              {!reachable
                ? t("err.offline_action")
                : !ready
                  ? waiting.length
                    ? t("deps.waiting", { titles: waiting.map((w) => `«${w.title}»`).join(", ") })
                    : childrenOpen
                    ? t("err.children_open")
                    : !stepsOk
                    ? t("err.steps_incomplete")
                    : t("err.proof_required")
                  : plan.approver
                    ? t("confirm.willNotify", { name: plan.approver.name })
                    : t("confirm.lockedHint")}
            </p>
          </div>
        </>
      )}
    </section>
  );
}

function Step({ n, ok, title, badge, children }: { n: number; ok: boolean; title: string; badge?: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3 rounded-2xl border border-line bg-surface p-3.5">
      <span
        aria-hidden="true"
        className={`flex h-7 w-7 flex-none items-center justify-center rounded-full text-[13px] font-extrabold ${ok ? "bg-ok-soft text-ok" : "bg-warn-soft text-warn-ink"}`}
      >
        {ok ? <Check size={14} /> : n}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-bold">{title}</span>
          {badge && <span className="text-[11px] font-semibold text-ink-muted">{badge}</span>}
        </div>
        {children}
      </div>
    </li>
  );
}

