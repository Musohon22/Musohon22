"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { loadPlans, loadStats, online, useT } from "@/lib/store";
import type { MessageKey } from "@/lib/i18n";
import { Check, Plus } from "../Icons";

const TEMPLATES: { key: string; count: number; colors: string[] }[] = [
  { key: "work_week", count: 4, colors: ["bg-card-yellow", "bg-card-sky", "bg-card-peach"] },
  { key: "student", count: 4, colors: ["bg-card-lilac", "bg-card-yellow", "bg-card-mint"] },
  { key: "sport", count: 3, colors: ["bg-card-mint", "bg-card-peach", "bg-card-mint"] },
  { key: "family", count: 3, colors: ["bg-card-peach", "bg-card-yellow", "bg-card-sky"] },
];

/** First run: a welcoming start instead of an empty grid. */
export function EmptyState({ onBlank }: { onBlank: () => void }) {
  const t = useT();
  const [busy, setBusy] = useState<string | null>(null);

  async function apply(key: string) {
    setBusy(key);
    const res = await online(() => api.post(`/api/templates/${key}/apply`));
    setBusy(null);
    if (res) {
      await loadPlans();
      void loadStats();
    }
  }

  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-4">
      <section className="pointer-events-auto w-full max-w-2xl animate-rise rounded-3xl border border-line bg-paper-2/95 p-6 shadow-lift backdrop-blur sm:p-8">
        <h2 className="font-display text-3xl font-extrabold tracking-tight">{t("empty.title")}</h2>
        <p className="mt-1 text-ink-3">{t("empty.lead")}</p>
        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {TEMPLATES.map((tpl) => (
            <button
              key={tpl.key}
              type="button"
              disabled={!!busy}
              onClick={() => void apply(tpl.key)}
              className="group flex flex-col gap-3 rounded-2xl border border-line bg-white p-3 text-left transition hover:-translate-y-0.5 hover:shadow-card disabled:opacity-60"
            >
              <span aria-hidden="true" className="relative h-14">
                {tpl.colors.map((c, i) => (
                  <span key={i} className={`absolute h-9 w-14 rounded-lg ${c} shadow-sm`} style={{ left: i * 18, top: i % 2 ? 14 : 2, transform: `rotate(${(i - 1) * 5}deg)` }} />
                ))}
              </span>
              <span>
                <span className="block font-bold">{t(`tpl.${tpl.key}` as MessageKey)}</span>
                <span className="text-xs text-ink-muted">{busy === tpl.key ? t("common.loading") : t("tpl.count", { n: tpl.count })}</span>
              </span>
            </button>
          ))}
        </div>
        <button type="button" onClick={onBlank} className="btn-dark mt-4 w-full sm:w-auto">
          <Plus size={16} />
          {t("empty.blank")}
        </button>
        <ul className="mt-6 grid gap-2 border-t border-dashed border-line-strong pt-5 text-sm text-ink-2 sm:grid-cols-3">
          {(["empty.tip1", "empty.tip2", "empty.tip3"] as const).map((k) => (
            <li key={k} className="flex gap-2">
              <Check size={16} className="mt-0.5 flex-none text-ok" />
              {t(k)}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
