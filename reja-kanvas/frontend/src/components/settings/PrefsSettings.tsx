"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { loadPlans, online, setUser, toast, useStore, useT } from "@/lib/store";
import type { MessageKey } from "@/lib/i18n";
import type { Prefs } from "@/lib/types";
import { REPLAY_TOUR } from "../Tour";
import { Section } from "./Section";

const KINDS = ["approval_requested", "returned", "approved", "mentioned", "approver_silent", "assigned", "due_soon", "commented"];
const DEFAULTS: Prefs = { email_kinds: ["approval_requested", "returned", "mentioned", "approver_silent", "assigned"], digest: false, quiet_start: null, quiet_end: null, large_text: false, high_contrast: false, onboarded: true };

/** Email, quiet hours and accessibility preferences, saved to the account. */
export function PrefsSettings() {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const [prefs, setPrefs] = useState<Prefs>({ ...DEFAULTS, ...(user.prefs ?? {}) });

  useEffect(() => {
    api.get<Prefs>("/api/me/prefs").then((p) => setPrefs({ ...DEFAULTS, ...p })).catch(() => undefined);
  }, []);

  async function save(next: Prefs) {
    setPrefs(next);
    const saved = await online(() => api.put<Prefs>("/api/me/prefs", next));
    if (saved) setUser({ ...user, prefs: saved });
  }

  return (
    <>
      <Section title={t("settings.emailNotif")}>
        <fieldset className="flex flex-col gap-2">
          <legend className="label mb-2">{t("settings.emailKinds")}</legend>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {KINDS.map((k) => (
              <label key={k} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-[18px] w-[18px] accent-accent"
                  checked={prefs.email_kinds.includes(k)}
                  onChange={(e) => void save({ ...prefs, email_kinds: e.target.checked ? [...prefs.email_kinds, k] : prefs.email_kinds.filter((x) => x !== k) })}
                />
                {t(`notifkind.${k}` as MessageKey)}
              </label>
            ))}
          </div>
        </fieldset>
        <label className="flex items-center gap-2 text-sm font-semibold">
          <input type="checkbox" className="h-[18px] w-[18px] accent-accent" checked={prefs.digest} onChange={(e) => void save({ ...prefs, digest: e.target.checked })} />
          {t("settings.digest")}
        </label>
        <fieldset className="flex flex-col gap-2">
          <legend className="label mb-1">{t("settings.quiet")}</legend>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5 text-sm">{t("settings.from")}
              <input type="time" className="field w-32" value={prefs.quiet_start ?? ""} onChange={(e) => void save({ ...prefs, quiet_start: e.target.value || null })} />
            </label>
            <label className="flex items-center gap-1.5 text-sm">{t("settings.to")}
              <input type="time" className="field w-32" value={prefs.quiet_end ?? ""} onChange={(e) => void save({ ...prefs, quiet_end: e.target.value || null })} />
            </label>
          </div>
          <span className="text-xs text-ink-muted">{t("settings.quietHint")}</span>
        </fieldset>
      </Section>

      <Section title={t("settings.accessibility")}>
        <label className="flex items-center gap-2 text-sm font-semibold">
          <input type="checkbox" className="h-[18px] w-[18px] accent-accent" checked={prefs.large_text} onChange={(e) => void save({ ...prefs, large_text: e.target.checked })} />
          {t("settings.largeText")}
        </label>
        <label className="flex items-center gap-2 text-sm font-semibold">
          <input type="checkbox" className="h-[18px] w-[18px] accent-accent" checked={prefs.high_contrast} onChange={(e) => void save({ ...prefs, high_contrast: e.target.checked })} />
          {t("settings.highContrast")}
        </label>
        <button type="button" className="btn self-start" onClick={() => window.dispatchEvent(new Event(REPLAY_TOUR))}>{t("settings.tour")}</button>
      </Section>
    </>
  );
}

export function ImportOther() {
  const t = useT();
  async function run(format: "csv" | "todoist" | "trello", file: File) {
    const content = await file.text();
    const r = await online(() => api.post<{ created: number; skipped: number }>("/api/import/external", { format, content }));
    if (r) {
      toast(t("settings.imported", { n: r.created, s: r.skipped }), { tone: "success" });
      void loadPlans();
    }
  }
  const pick = (format: "csv" | "todoist" | "trello", accept: string) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = accept;
    input.onchange = () => input.files?.[0] && void run(format, input.files[0]);
    input.click();
  };
  return (
    <Section title={t("settings.importOther")}>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn" onClick={() => pick("csv", ".csv,text/csv")}>{t("settings.importCsv")}</button>
        <button type="button" className="btn" onClick={() => pick("todoist", ".csv,text/csv")}>{t("settings.importTodoist")}</button>
        <button type="button" className="btn" onClick={() => pick("trello", ".json,application/json")}>{t("settings.importTrello")}</button>
      </div>
    </Section>
  );
}
