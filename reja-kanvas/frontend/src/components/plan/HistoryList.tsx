"use client";

import { hasKey } from "@/lib/i18n";
import { useStore, useT } from "@/lib/store";
import { fmtDateTime } from "@/lib/time";
import type { PlanEvent } from "@/lib/types";

const QUIET = new Set(["edited"]);

export function HistoryList({ events }: { events: PlanEvent[] }) {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  // Collapse runs of plain edits so the history stays readable.
  const shown = events.filter((e, i) => !(QUIET.has(e.kind) && events[i - 1]?.kind === e.kind));

  return (
    <ol className="relative flex flex-col gap-3 border-l-2 border-line pl-4">
      {shown.map((e) => {
        const key = `ev.${e.kind}`;
        const vars = Object.fromEntries(Object.entries(e.data).map(([k, v]) => [k, String(v ?? "")]));
        const who = e.user_name ?? (e.data.via === "share" ? t("ev.guest") : t("ev.system"));
        return (
          <li key={e.id} className="relative">
            <span aria-hidden="true" className="absolute -left-[23px] top-1.5 h-3 w-3 rounded-full border-2 border-paper-2 bg-ink-muted" />
            <div className="text-sm font-semibold">{hasKey(key) ? t(key, vars) : e.kind}</div>
            <div className="text-xs text-ink-muted">{who} · {fmtDateTime(e.created_at, user.tz, lang)}</div>
          </li>
        );
      })}
    </ol>
  );
}
