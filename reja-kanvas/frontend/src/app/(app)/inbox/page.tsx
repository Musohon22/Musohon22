"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { hasKey } from "@/lib/i18n";
import { loadStats, online, useStore, useT } from "@/lib/store";
import { fmtDateTime, fmtTime } from "@/lib/time";
import type { Notification, Plan } from "@/lib/types";

export default function InboxPage() {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const [approvals, setApprovals] = useState<Plan[] | null>(null);
  const [notes, setNotes] = useState<Notification[] | null>(null);

  const load = useCallback(() => {
    api.get<{ plans: Plan[] }>("/api/approvals").then((r) => setApprovals(r.plans)).catch(() => setApprovals((a) => a ?? []));
    api.get<{ notifications: Notification[] }>("/api/notifications").then((r) => setNotes(r.notifications)).catch(() => setNotes((n) => n ?? []));
  }, []);

  useEffect(load, [load]);

  async function markAll() {
    const ok = await online(async () => {
      await api.post("/api/notifications/read", {});
      return true;
    });
    if (ok) {
      setNotes((n) => n?.map((x) => ({ ...x, read_at: x.read_at ?? new Date().toISOString() })) ?? null);
      void loadStats();
    }
  }

  function text(n: Notification) {
    const kind = n.kind === "approver_silent" && n.data.has_backup ? "approver_silent_backup" : n.kind;
    const key = `notif.${kind}`;
    const vars = {
      title: n.data.title ?? "",
      reason: n.data.reason ?? "",
      time: n.data.due_at ? fmtTime(n.data.due_at, user.tz, lang) : "",
    };
    return hasKey(key) ? t(key, vars) : n.kind;
  }

  const unread = notes?.filter((n) => !n.read_at).length ?? 0;

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-10 px-4 py-8 sm:px-6">
      <h1 className="font-display text-3xl font-extrabold tracking-tight">{t("inbox.title")}</h1>

      <section aria-labelledby="approvals" className="flex flex-col gap-3">
        <h2 id="approvals" className="eyebrow">{t("inbox.approvals")}</h2>
        {approvals === null && <p className="text-ink-muted">{t("common.loading")}</p>}
        {approvals?.length === 0 && <p className="rounded-xl border border-dashed border-line-strong p-5 text-ink-muted">{t("inbox.noApprovals")}</p>}
        {approvals?.map((p) => (
          <Link key={p.id} href={`/plan/${p.id}#confirm`} className="flex items-center gap-4 rounded-2xl border border-line bg-white p-4 hover:shadow-card">
            <span className="flex h-11 w-11 flex-none items-center justify-center rounded-full bg-[#9FC3FF] font-extrabold text-[#0E2A66]">
              {p.owner?.name.slice(0, 1).toUpperCase()}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-bold">{p.title}</span>
              <span className="text-sm text-ink-muted">{t("inbox.from", { name: p.owner?.name ?? "—", time: p.submitted_at ? fmtDateTime(p.submitted_at, user.tz, lang) : "" })}</span>
            </span>
            {p.escalated_at && p.backup_approver_id === user.id && <span className="chip bg-warn-soft text-warn-ink">{t("inbox.escalatedBadge")}</span>}
          </Link>
        ))}
      </section>

      <section aria-labelledby="notes" className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-4">
          <h2 id="notes" className="eyebrow">{t("inbox.notifications")}</h2>
          {unread > 0 && <button type="button" className="text-sm font-bold text-accent-ink underline underline-offset-2" onClick={() => void markAll()}>{t("inbox.markAll")}</button>}
        </div>
        {notes?.length === 0 && <p className="text-ink-muted">{t("inbox.empty")}</p>}
        <ul className="flex flex-col gap-2">
          {notes?.map((n) => (
            <li key={n.id}>
              <Link
                href={n.plan_id ? `/plan/${n.plan_id}` : "/inbox"}
                className={`flex gap-3 rounded-xl border p-3.5 ${n.read_at ? "border-line-soft bg-paper-2" : "border-line bg-white font-semibold"}`}
              >
                {!n.read_at && <span aria-hidden="true" className="mt-1.5 h-2.5 w-2.5 flex-none rounded-full bg-warn" />}
                <span className="min-w-0 flex-1">
                  <span className="block text-[15px]">{text(n)}</span>
                  <span className="text-xs font-normal text-ink-muted">{fmtDateTime(n.created_at, user.tz, lang)}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
