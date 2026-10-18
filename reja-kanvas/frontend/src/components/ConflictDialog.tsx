"use client";

import { useEffect, useState } from "react";
import { resolveConflict, useStore, useT } from "@/lib/store";
import { fmtDateTime } from "@/lib/time";
import type { PlanChanges } from "@/lib/types";
import type { MessageKey } from "@/lib/i18n";
import { Dialog } from "./Dialog";

function show(field: keyof PlanChanges, value: unknown, tz: string, lang: Parameters<typeof fmtDateTime>[2], empty: string): string {
  if (value === null || value === undefined || value === "") return empty;
  if (field === "body_html") {
    // DOMParser never runs scripts or loads resources, unlike innerHTML on a live element.
    const text = new DOMParser().parseFromString(String(value), "text/html").body.textContent ?? "";
    return text.length > 160 ? text.slice(0, 160) + "…" : text || empty;
  }
  if (field === "due_at") return fmtDateTime(String(value), tz, lang);
  return String(value);
}

/** Two devices edited the same field: the user picks, per field, which version stays. */
export function ConflictDialog() {
  const t = useT();
  const conflict = useStore((s) => s.conflicts[0]);
  const user = useStore((s) => s.user);
  const lang = useStore((s) => s.lang);
  const [keepMine, setKeepMine] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (conflict) setKeepMine(Object.fromEntries(conflict.fields.map((f) => [f, true])));
  }, [conflict]);

  if (!conflict || !user) return null;
  const tz = user.tz;
  return (
    <Dialog open title={t("conflict.title")} onClose={() => resolveConflict(conflict.planId, [])} wide dismissable={false}>
      <p className="text-ink-3">{t("conflict.lead")}</p>
      <div className="flex flex-col gap-4">
        {conflict.fields.map((field) => (
          <fieldset key={field} className="rounded-xl border border-line bg-surface p-4">
            <legend className="px-1 text-sm font-bold">{t(`field.${field}` as MessageKey)}</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {[true, false].map((mine) => (
                <label
                  key={String(mine)}
                  className={`flex cursor-pointer flex-col gap-1 rounded-lg border-2 p-3 ${keepMine[field] === mine ? "border-accent bg-accent-soft" : "border-line-soft"}`}
                >
                  <span className="flex items-center gap-2 text-sm font-bold">
                    <input
                      type="radio"
                      name={`c-${field}`}
                      checked={keepMine[field] === mine}
                      onChange={() => setKeepMine((k) => ({ ...k, [field]: mine }))}
                      className="h-4 w-4 accent-accent"
                    />
                    {mine ? t("conflict.mine") : t("conflict.theirs")}
                  </span>
                  <span className="break-words text-sm text-ink-2">
                    {show(field, mine ? conflict.mine[field] : conflict.server[field], tz, lang, t("common.empty"))}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
        ))}
      </div>
      <div className="flex justify-end">
        <button
          type="button"
          className="btn-primary"
          onClick={() => resolveConflict(conflict.planId, conflict.fields.filter((f) => keepMine[f]))}
        >
          {t("conflict.apply")}
        </button>
      </div>
    </Dialog>
  );
}
