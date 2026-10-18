"use client";

import { describeRecurrence } from "@/lib/recurrence";
import { useT } from "@/lib/store";
import type { MessageKey } from "@/lib/i18n";
import type { Recurrence } from "@/lib/types";

export function RecurrencePicker({
  value, disabled, hasDue, onChange,
}: {
  value: Recurrence | null;
  disabled: boolean;
  hasDue: boolean;
  onChange: (r: Recurrence | null) => void;
}) {
  const t = useT();
  const set = (patch: Partial<Recurrence>) => onChange({ freq: "daily", interval: 1, weekdays: [], until: null, ...value, ...patch });

  return (
    <fieldset className="flex flex-col gap-2 sm:col-span-2" disabled={disabled}>
      <legend className="label mb-1.5">{t("rec.label")}</legend>
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="field w-auto"
          aria-label={t("rec.label")}
          value={value?.freq ?? ""}
          disabled={disabled || (!hasDue && !value)}
          onChange={(e) => (e.target.value ? set({ freq: e.target.value as Recurrence["freq"], weekdays: [] }) : onChange(null))}
        >
          <option value="">{t("rec.none")}</option>
          <option value="daily">{t("rec.daily")}</option>
          <option value="weekly">{t("rec.weekly")}</option>
          <option value="monthly">{t("rec.monthly")}</option>
        </select>
        {value && (
          <>
            <label className="flex items-center gap-1.5 text-sm">
              <span className="text-ink-muted">{t("rec.interval")}</span>
              <input
                type="number"
                min={1}
                max={30}
                className="field w-20"
                value={value.interval}
                onChange={(e) => set({ interval: Math.min(30, Math.max(1, Number(e.target.value) || 1)) })}
              />
            </label>
            <label className="flex items-center gap-1.5 text-sm">
              <span className="text-ink-muted">{t("rec.until")}</span>
              <input type="date" className="field w-auto" value={value.until ?? ""} onChange={(e) => set({ until: e.target.value || null })} />
            </label>
          </>
        )}
      </div>
      {value?.freq === "weekly" && (
        <div role="group" aria-label={t("rec.weekdays")} className="flex flex-wrap gap-1">
          {[0, 1, 2, 3, 4, 5, 6].map((d) => {
            const on = value.weekdays.includes(d);
            return (
              <button
                key={d}
                type="button"
                aria-pressed={on}
                onClick={() => set({ weekdays: on ? value.weekdays.filter((x) => x !== d) : [...value.weekdays, d].sort() })}
                className={`h-10 w-11 rounded-lg border text-sm font-bold ${on ? "border-accent bg-accent text-white" : "border-line bg-surface text-ink-2"}`}
              >
                {t(`wd.${d}` as MessageKey)}
              </button>
            );
          })}
        </div>
      )}
      {value && <p className="text-xs text-ink-muted">{describeRecurrence(value, t)}</p>}
      {!value && !hasDue && <p className="text-xs text-ink-muted">{t("rec.needsDue")}</p>}
    </fieldset>
  );
}
