"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { needsConfirmPanel, submitWithUndo } from "@/lib/actions";
import { useStore, useT } from "@/lib/store";
import { fmtDate, fmtTime, zoneOf, type Zone } from "@/lib/time";
import type { MessageKey } from "@/lib/i18n";
import type { Plan } from "@/lib/types";
import { Check, Grid, Lock } from "@/components/Icons";
import { CARD_BG } from "@/components/canvas/PlanCard";
import { FilterBar } from "@/components/FilterBar";
import { matches } from "@/lib/filter";

const SECTIONS: { key: Zone | "finished"; label: MessageKey }[] = [
  { key: "overdue", label: "list.overdue" },
  { key: "today", label: "list.today" },
  { key: "tomorrow", label: "list.tomorrow" },
  { key: "week", label: "list.week" },
  { key: "later", label: "list.later" },
  { key: "none", label: "list.noDue" },
  { key: "finished", label: "list.finished" },
];

/** The same plans as a plain list: keyboard and screen-reader friendly, good on small phones. */
export default function ListPage() {
  const t = useT();
  const router = useRouter();
  const planMap = useStore((s) => s.plans);
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const loaded = useStore((s) => s.loaded);
  const filter = useStore((s) => s.filter);
  const hasTeams = useStore((s) => s.boards.some((b) => b.team_id));

  const groups = useMemo(() => {
    const out: Record<string, Plan[]> = {};
    for (const p of Object.values(planMap)) {
      if (!matches(p, filter, user.tz, user.id)) continue;
      const key = p.status === "done" || p.status === "cancelled" ? "finished" : zoneOf(p, user.tz);
      (out[key] ??= []).push(p);
    }
    for (const list of Object.values(out)) list.sort((a, b) => (a.due_at ?? "9999").localeCompare(b.due_at ?? "9999"));
    out.finished?.sort((a, b) => (b.completed_at ?? b.updated_at).localeCompare(a.completed_at ?? a.updated_at));
    return out;
  }, [planMap, user.tz, user.id, filter]);

  const empty = loaded && Object.keys(planMap).length === 0;
  const [archive, setArchive] = useState<Plan[] | null>(null);
  const toggleArchive = () => {
    if (archive) return setArchive(null);
    api.get<{ plans: Plan[] }>("/api/plans?archived=1").then((r) => setArchive(r.plans)).catch(() => setArchive([]));
  };

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-8 sm:px-6">
      <FilterBar teamMode={hasTeams} />
      {empty && (
        <div className="flex flex-col items-center gap-4 rounded-2xl border border-line bg-surface p-10 text-center">
          <p className="text-lg font-semibold text-ink-3">{t("list.empty")}</p>
          <Link href="/canvas" className="btn-primary"><Grid size={16} />{t("nav.canvas")}</Link>
        </div>
      )}
      {SECTIONS.map(({ key, label }) => {
        const items = groups[key];
        if (!items?.length) return null;
        return (
          <section key={key} aria-labelledby={`sec-${key}`} className="flex flex-col gap-2">
            <h2 id={`sec-${key}`} className={`font-display text-xl font-bold ${key === "overdue" ? "text-warn-strong" : ""}`}>
              {t(label)} <span className="font-sans text-sm font-semibold text-ink-muted">· {items.length}</span>
            </h2>
            <ul className="flex flex-col gap-2">
              {items.map((p) => {
                const open = p.status === "active" || p.status === "returned";
                return (
                  <li key={p.id} className="flex items-center gap-3 rounded-xl border border-line bg-surface p-2 pr-3">
                    <button
                      type="button"
                      disabled={!open}
                      aria-label={`${t("card.done")}: ${p.title}`}
                      onClick={() => (needsConfirmPanel(p) ? router.push(`/plan/${p.id}#confirm`) : void submitWithUndo(p.id))}
                      className={`flex h-11 w-11 flex-none items-center justify-center rounded-xl border-2 ${
                        p.status === "done" ? "border-ok bg-ok text-white" : open ? "border-line-strong text-transparent hover:border-ok hover:text-ok" : "border-line text-ink-muted"
                      }`}
                    >
                      {p.status === "pending_approval" ? <Lock size={16} className="text-accent-ink" /> : <Check size={18} />}
                    </button>
                    <span aria-hidden="true" className={`h-8 w-1.5 flex-none rounded-full ${CARD_BG[p.color]}`} />
                    <Link href={`/plan/${p.id}`} className="min-w-0 flex-1 py-1">
                      <span className={`block truncate font-semibold ${p.status === "done" || p.status === "cancelled" ? "text-ink-muted line-through" : ""}`}>{p.title}</span>
                      <span className="flex flex-wrap gap-x-3 text-xs text-ink-muted">
                        {p.tag && <span>{p.tag}</span>}
                        {p.progress.total > 0 && <span>{p.progress.done}/{p.progress.total}</span>}
                        {p.status !== "active" && <span className={p.status === "returned" ? "font-bold text-warn-strong" : ""}>{t(`status.${p.status}`)}</span>}
                      </span>
                    </Link>
                    {p.due_at && (
                      <span className={`whitespace-nowrap font-mono text-xs ${key === "overdue" ? "font-bold text-warn-strong" : "text-ink-muted"}`}>
                        {key === "today" ? fmtTime(p.due_at, user.tz, lang) : fmtDate(p.due_at, user.tz, lang)}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
      <section className="flex flex-col gap-2 border-t border-dashed border-line-strong pt-6">
        <button type="button" className="self-start text-sm font-bold text-accent-ink underline underline-offset-2" aria-expanded={!!archive} onClick={toggleArchive}>
          {archive ? t("list.hideArchive") : t("list.showArchive")}
        </button>
        {archive?.length === 0 && <p className="text-sm text-ink-muted">{t("list.empty")}</p>}
        <ul className="flex flex-col gap-2">
          {archive?.map((p) => (
            <li key={p.id}>
              <Link href={`/plan/${p.id}`} className="flex items-center gap-3 rounded-xl border border-line-soft bg-paper-2 p-3 text-ink-3">
                <span aria-hidden="true" className={`h-6 w-1.5 flex-none rounded-full ${CARD_BG[p.color]}`} />
                <span className="min-w-0 flex-1 truncate line-through">{p.title}</span>
                <span className="text-xs">{t(`status.${p.status}`)}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
