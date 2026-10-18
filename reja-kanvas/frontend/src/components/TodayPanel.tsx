"use client";

import Link from "next/link";
import { useStore, useT } from "@/lib/store";
import { fmtTime, zoneOf } from "@/lib/time";
import type { Plan } from "@/lib/types";
import { Flame } from "./Icons";

const DOT: Record<Plan["color"], string> = {
  yellow: "bg-[#F2C230]", mint: "bg-[#3DB37A]", lilac: "bg-[#7D6BE0]", peach: "bg-[#FF9B66]", sky: "bg-[#6B8CFF]", white: "bg-[#A9A190]",
};

export function TodayPanel({ plans }: { plans: Plan[] }) {
  const t = useT();
  const stats = useStore((s) => s.stats);
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);

  const total = stats?.today_total ?? 0;
  const done = stats?.today_done ?? 0;
  const pct = total ? done / total : 0;
  const C = 2 * Math.PI * 50;
  const next = plans
    .filter((p) => (p.status === "active" || p.status === "returned") && p.due_at && ["today", "overdue"].includes(zoneOf(p, user.tz)))
    .sort((a, b) => a.due_at!.localeCompare(b.due_at!))
    .slice(0, 4);

  const headline = !total ? t("today.empty") : done === total ? t("today.allDone") : done === 0 ? t("today.start") : t("today.goodPace");

  return (
    <aside className="flex w-full flex-col gap-6 border-t border-line bg-paper-2 p-5 lg:w-[320px] lg:flex-none lg:border-l lg:border-t-0 lg:p-6">
      <section>
        <h2 className="eyebrow">{t("today.title")}</h2>
        <div className="mt-3 flex items-center gap-4">
          <svg width="112" height="112" viewBox="0 0 120 120" role="img" aria-label={t("today.ring", { done, total })}>
            <circle cx="60" cy="60" r="50" fill="none" stroke="#E6E0D3" strokeWidth="12" />
            <circle
              cx="60" cy="60" r="50" fill="none" stroke="#2B59FF" strokeWidth="12" strokeLinecap="round"
              strokeDasharray={`${pct * C} ${C}`} transform="rotate(-90 60 60)" style={{ transition: "stroke-dasharray .5s" }}
            />
            <text x="60" y="60" textAnchor="middle" className="fill-ink font-display" fontWeight="800" fontSize="28">{done}/{total}</text>
            <text x="60" y="80" textAnchor="middle" className="fill-ink-muted" fontWeight="600" fontSize="12">{t("today.done")}</text>
          </svg>
          <div className="flex min-w-0 flex-col gap-2">
            <div className="font-display text-xl font-bold leading-tight">{headline}</div>
            {total > done && <div className="text-sm text-ink-3">{t("today.left", { n: total - done })}</div>}
            {(stats?.streak ?? 0) > 0 && (
              <div className="chip self-start bg-warn-soft text-warn-ink"><Flame size={13} />{t("today.streak", { n: stats!.streak })}</div>
            )}
          </div>
        </div>
        {(stats?.streak ?? 0) > 0 && (
          <p className="mt-3 text-xs text-ink-muted">{stats!.freeze_used_this_week ? t("today.freezeUsed") : t("today.freezeAvailable")}</p>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="eyebrow">{t("today.next")}</h2>
        {next.length === 0 && <p className="text-sm text-ink-muted">{t("today.nothingNext")}</p>}
        {next.map((p) => (
          <Link
            key={p.id}
            href={`/plan/${p.id}`}
            className="flex items-center gap-3 rounded-xl border border-line-soft bg-white px-3 py-2.5 hover:border-line-strong"
          >
            <span className={`w-11 font-mono text-xs ${new Date(p.due_at!) < new Date() ? "font-bold text-warn-strong" : "text-ink-muted"}`}>
              {fmtTime(p.due_at!, user.tz, lang)}
            </span>
            <span className="min-w-0 flex-1 truncate text-sm font-semibold">{p.title}</span>
            <span aria-hidden="true" className={`h-2.5 w-2.5 flex-none rounded-full ${DOT[p.color]}`} />
          </Link>
        ))}
      </section>

      {(stats?.awaiting_my_approval ?? 0) > 0 && (
        <section className="flex flex-col gap-3 rounded-2xl bg-ink p-5 text-paper">
          <div className="text-xs font-bold uppercase tracking-[0.08em] text-[#CFC9BC]">{t("inbox.approvals")}</div>
          <div className="font-display text-lg font-bold leading-snug">{t("today.awaiting", { n: stats!.awaiting_my_approval })}</div>
          <Link href="/inbox" className="flex h-11 items-center justify-center rounded-xl bg-paper font-extrabold text-ink">{t("today.open")}</Link>
        </section>
      )}
    </aside>
  );
}
