"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, API_URL, getToken, setToken } from "@/lib/api";
import { LANGS } from "@/lib/i18n";
import { loadPlans, loadStats, online, setUser, signOut, toast, toastError, useStore, useT } from "@/lib/store";
import { getTheme, setTheme, type Theme } from "@/lib/theme";
import type { Lang, User } from "@/lib/types";
import { Copy } from "@/components/Icons";

const NOTIFY_KEY = "reja.notify";

function Card({ title, children, danger = false }: { title: string; children: React.ReactNode; danger?: boolean }) {
  return (
    <section className={`flex flex-col gap-4 rounded-2xl border bg-surface p-6 ${danger ? "border-warn/40" : "border-line"}`}>
      <h2 className={`font-display text-lg font-bold ${danger ? "text-warn-strong" : ""}`}>{title}</h2>
      {children}
    </section>
  );
}

async function download(path: string, filename: string) {
  const res = await fetch(`${API_URL}${path}`, { headers: { Authorization: `Bearer ${getToken()}` } });
  if (!res.ok) throw new Error(String(res.status));
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

export default function SettingsPage() {
  const t = useT();
  const router = useRouter();
  const user = useStore((s) => s.user)!;
  const [name, setName] = useState(user.name);
  const [tz, setTz] = useState(user.tz);
  const [lang, setLangValue] = useState<Lang>(user.lang);
  const [busy, setBusy] = useState(false);
  const [theme, setThemeState] = useState<Theme>("system");
  const [notify, setNotify] = useState<"off" | "on" | "blocked" | "unsupported">("off");
  const [calUrl, setCalUrl] = useState<string | null>(null);
  const [pw, setPw] = useState({ current: "", next: "" });
  const [delPw, setDelPw] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setThemeState(getTheme());
    if (typeof Notification === "undefined") return setNotify("unsupported");
    if (Notification.permission === "denied") return setNotify("blocked");
    let on = false;
    try {
      on = localStorage.getItem(NOTIFY_KEY) === "1";
    } catch {
      /* ignore */
    }
    setNotify(on && Notification.permission === "granted" ? "on" : "off");
  }, []);

  const zones = useMemo(() => {
    try {
      return (Intl as unknown as { supportedValuesOf(k: string): string[] }).supportedValuesOf("timeZone");
    } catch {
      return [user.tz, "Asia/Tashkent", "Asia/Samarkand", "Europe/Moscow", "UTC"];
    }
  }, [user.tz]);

  async function saveProfile(e: React.FormEvent) {
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

  async function enableNotifications() {
    const permission = await Notification.requestPermission();
    if (permission === "granted") {
      try {
        localStorage.setItem(NOTIFY_KEY, "1");
      } catch {
        /* ignore */
      }
      setNotify("on");
    } else setNotify(permission === "denied" ? "blocked" : "off");
  }

  async function showCalendar(rotate = false) {
    const r = await online(() => (rotate ? api.post<{ token: string }>("/api/me/calendar") : api.get<{ token: string }>("/api/me/calendar")));
    if (r) setCalUrl(`${API_URL}/api/calendar/${r.token}.ics`);
  }

  async function importFile(file: File) {
    let data: unknown;
    try {
      data = JSON.parse(await file.text());
    } catch {
      return toast(t("settings.importBad"), { tone: "error" });
    }
    if (!data || typeof data !== "object" || !Array.isArray((data as { plans?: unknown }).plans)) {
      return toast(t("settings.importBad"), { tone: "error" });
    }
    const r = await online(() => api.post<{ created: number; skipped: number }>("/api/import", { version: 1, plans: (data as { plans: unknown[] }).plans }));
    if (r) {
      toast(t("settings.imported", { n: r.created, s: r.skipped }), { tone: "success" });
      void loadPlans();
    }
  }

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    const r = await online(() => api.post<{ token: string }>("/api/me/password", { current: pw.current, new: pw.next }));
    if (r) {
      setToken(r.token);
      setPw({ current: "", next: "" });
      toast(t("settings.passwordChanged"), { tone: "success" });
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-8 sm:px-6">
      <h1 className="font-display text-3xl font-extrabold tracking-tight">{t("settings.title")}</h1>

      <Card title={t("settings.account")}>
        <form onSubmit={saveProfile} className="flex flex-col gap-4">
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
          <div className="text-sm text-ink-muted">{user.email}</div>
          <button className="btn-primary self-start" disabled={busy || !name.trim()}>{t("common.save")}</button>
        </form>
      </Card>

      <Card title={t("settings.theme")}>
        <div role="radiogroup" aria-label={t("settings.theme")} className="flex flex-wrap gap-2">
          {(["system", "light", "dark"] as Theme[]).map((v) => (
            <button
              key={v}
              type="button"
              role="radio"
              aria-checked={theme === v}
              onClick={() => {
                setTheme(v);
                setThemeState(v);
              }}
              className={`h-11 rounded-xl border-2 px-4 text-sm font-bold ${theme === v ? "border-accent bg-accent-soft text-accent-ink" : "border-line"}`}
            >
              {t(`theme.${v}`)}
            </button>
          ))}
        </div>
      </Card>

      <Card title={t("settings.notifications")}>
        <p className="text-sm text-ink-3">{t("settings.notifHint")}</p>
        {notify === "on" && <p className="font-semibold text-ok">{t("settings.notifOn")}</p>}
        {notify === "blocked" && <p className="text-sm font-semibold text-warn-strong">{t("settings.notifBlocked")}</p>}
        {notify === "off" && <button type="button" className="btn self-start" onClick={() => void enableNotifications()}>{t("settings.notifEnable")}</button>}
      </Card>

      <Card title={t("settings.calendar")}>
        <p className="text-sm text-ink-3">{t("settings.calendarHint")}</p>
        {calUrl ? (
          <div className="flex flex-col gap-2">
            <div className="flex gap-2">
              <label className="flex-1">
                <span className="sr-only">{t("settings.calendar")}</span>
                <input readOnly className="field font-mono text-xs" value={calUrl} onFocus={(e) => e.target.select()} />
              </label>
              <button
                type="button"
                className="btn"
                onClick={() => navigator.clipboard.writeText(calUrl).then(() => toast(t("share.copied"), { tone: "success" }), () => undefined)}
              >
                <Copy size={16} />{t("share.copy")}
              </button>
            </div>
            <button type="button" className="self-start text-sm font-semibold text-warn-strong underline underline-offset-2" onClick={() => void showCalendar(true)}>
              {t("settings.rotate")}
            </button>
          </div>
        ) : (
          <button type="button" className="btn self-start" onClick={() => void showCalendar()}>{t("settings.calendarShow")}</button>
        )}
      </Card>

      <Card title={t("settings.data")}>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn" onClick={() => download("/api/export.json", "reja-export.json").catch(toastError)}>{t("settings.exportJson")}</button>
          <button type="button" className="btn" onClick={() => download("/api/export.csv", "reja-export.csv").catch(toastError)}>{t("settings.exportCsv")}</button>
          <button type="button" className="btn" onClick={() => fileInput.current?.click()}>{t("settings.import")}</button>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            className="sr-only"
            tabIndex={-1}
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void importFile(f);
            }}
          />
        </div>
        <button
          type="button"
          className="self-start text-sm font-semibold text-accent-ink underline underline-offset-2"
          onClick={async () => {
            const r = await online(() => api.post<{ archived: number }>("/api/plans/archive-finished"));
            if (r) {
              toast(t("settings.archivedN", { n: r.archived }), { tone: "success" });
              void loadPlans();
            }
          }}
        >
          {t("settings.archiveFinished")}
        </button>
      </Card>

      <Card title={t("settings.security")}>
        <form onSubmit={changePassword} className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5">
            <span className="label">{t("settings.currentPassword")}</span>
            <input type="password" autoComplete="current-password" className="field" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="label">{t("settings.newPassword")}</span>
            <input type="password" autoComplete="new-password" minLength={8} className="field" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
            <span className="text-xs text-ink-muted">{t("auth.passwordHint")}</span>
          </label>
          <button className="btn-dark self-start" disabled={!pw.current || pw.next.length < 8}>{t("settings.changePassword")}</button>
        </form>
        <button
          type="button"
          className="btn self-start"
          onClick={async () => {
            const r = await online(() => api.post<{ token: string }>("/api/me/logout-all"));
            if (r) {
              setToken(r.token);
              toast(t("settings.loggedOutAll"), { tone: "success" });
            }
          }}
        >
          {t("settings.logoutAll")}
        </button>
      </Card>

      <Card title={t("settings.danger")} danger>
        <p className="text-sm text-ink-3">{t("settings.deleteHint")}</p>
        <form
          className="flex flex-wrap gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            const ok = await online(async () => {
              await api.del("/api/me", { body: { password: delPw } });
              return true;
            });
            if (ok) {
              signOut();
              router.replace("/login");
            }
          }}
        >
          <label className="min-w-0 flex-1">
            <span className="sr-only">{t("auth.password")}</span>
            <input type="password" autoComplete="current-password" className="field" placeholder={t("auth.password")} value={delPw} onChange={(e) => setDelPw(e.target.value)} />
          </label>
          <button className="btn-danger" disabled={!delPw}>{t("settings.deleteAccount")}</button>
        </form>
      </Card>
    </main>
  );
}
