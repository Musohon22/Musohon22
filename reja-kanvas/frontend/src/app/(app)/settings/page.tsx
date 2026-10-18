"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { LANGS } from "@/lib/i18n";
import { loadStats, online, setUser, toast, useStore, useT } from "@/lib/store";
import type { Lang, User } from "@/lib/types";

export default function SettingsPage() {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const [name, setName] = useState(user.name);
  const [tz, setTz] = useState(user.tz);
  const [lang, setLangValue] = useState<Lang>(user.lang);
  const [busy, setBusy] = useState(false);

  const zones = useMemo(() => {
    try {
      return (Intl as unknown as { supportedValuesOf(k: string): string[] }).supportedValuesOf("timeZone");
    } catch {
      return [user.tz, "Asia/Tashkent", "Asia/Samarkand", "Europe/Moscow", "UTC"];
    }
  }, [user.tz]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const updated = await online(() => api.patch<User>("/api/me", { name: name.trim(), tz, lang }));
    setBusy(false);
    if (updated) {
      setUser(updated);
      void loadStats();
      toast(t("settings.saved"), { tone: "success" });
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-xl flex-col gap-6 px-4 py-8 sm:px-6">
      <h1 className="font-display text-3xl font-extrabold tracking-tight">{t("settings.title")}</h1>
      <form onSubmit={save} className="flex flex-col gap-5 rounded-2xl border border-line bg-white p-6">
        <label className="flex flex-col gap-1.5">
          <span className="label">{t("settings.name")}</span>
          <input className="field" value={name} maxLength={80} required onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="label">{t("settings.lang")}</span>
          <select className="field" value={lang} onChange={(e) => setLangValue(e.target.value as Lang)}>
            {LANGS.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="label">{t("settings.tz")}</span>
          <select className="field" value={tz} onChange={(e) => setTz(e.target.value)}>
            {zones.map((z) => <option key={z} value={z}>{z}</option>)}
          </select>
          <span className="text-xs text-ink-muted">{t("settings.tzHint")}</span>
        </label>
        <div className="text-sm text-ink-muted">{t("settings.account")}: {user.email}</div>
        <button className="btn-primary self-start" disabled={busy || !name.trim()}>{t("common.save")}</button>
      </form>
    </main>
  );
}
