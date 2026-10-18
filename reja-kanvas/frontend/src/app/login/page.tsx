"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { LANGS } from "@/lib/i18n";
import { errorText, setLang, signedIn, useStore, useT } from "@/lib/store";
import { browserTimeZone } from "@/lib/time";
import type { Lang, User } from "@/lib/types";
import { Check, Logo } from "@/components/Icons";

export default function LoginPage() {
  const t = useT();
  const router = useRouter();
  const lang = useStore((s) => s.lang);
  const user = useStore((s) => s.user);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [needCode, setNeedCode] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (user) router.replace("/canvas");
  }, [user, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res =
        mode === "login"
          ? await api.post<{ token: string; user: User }>("/api/auth/login", { email, password, ...(needCode ? { code } : {}) }, { auth: false })
          : await api.post<{ token: string; user: User }>(
              "/api/auth/register",
              { email, name, password, tz: browserTimeZone(), lang },
              { auth: false },
            );
      signedIn(res.token, res.user);
      router.replace("/canvas");
    } catch (err) {
      if (err instanceof ApiError && err.code === "totp_required") {
        setNeedCode(true);
        setError(null);
        return;
      }
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-dvh lg:grid-cols-[1fr_520px]">
      <section className="canvas-dots relative hidden overflow-hidden bg-[length:22px_22px] p-12 lg:flex lg:flex-col lg:justify-between">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-ink text-paper"><Logo size={22} /></span>
          <span className="font-display text-2xl font-extrabold tracking-tight">Reja<span className="text-accent">.</span></span>
        </div>
        <div aria-hidden="true" className="relative mx-auto h-[360px] w-[560px]">
          <div className="absolute left-0 top-6 w-64 -rotate-2 card-scope rounded-2xl bg-card-yellow p-4 text-ink shadow-card">
            <div className="font-mono text-xs text-[#6B4E00]">15:00</div>
            <div className="mt-1 font-display text-xl font-bold">Mijozga taqdimot</div>
            <div className="mt-3 h-1.5 rounded bg-black/10"><div className="h-1.5 w-3/5 rounded bg-ink" /></div>
          </div>
          <div className="absolute right-6 top-0 w-60 rotate-2 card-scope rounded-2xl bg-card-mint p-4 text-ink shadow-card">
            <div className="font-display text-xl font-bold text-[#4A5A50] line-through decoration-2">Yugurish — 5 km</div>
            <div className="absolute -right-3 -top-3 flex -rotate-12 items-center gap-1 rounded-lg border-[2.5px] border-ok bg-card-mint px-2 py-1 font-display text-sm font-extrabold tracking-widest text-ok">
              <Check size={14} />BAJARILDI
            </div>
          </div>
          <div className="absolute bottom-0 left-40 w-64 rotate-[-4deg] card-scope rounded-2xl bg-card-lilac p-4 text-ink shadow-lift">
            <div className="text-xs font-bold text-[#3E2A9E]">Har kuni</div>
            <div className="mt-1 font-display text-xl font-bold">Kitob: 30 sahifa</div>
          </div>
        </div>
        <ul className="flex flex-col gap-3 text-lg font-semibold">
          {(["auth.pitch1", "auth.pitch2", "auth.pitch3"] as const).map((k) => (
            <li key={k} className="flex items-center gap-3">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-ink text-paper"><Check size={14} /></span>
              {t(k)}
            </li>
          ))}
        </ul>
      </section>

      <section className="flex flex-col justify-center gap-8 bg-paper-2 px-6 py-10 sm:px-12">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 lg:hidden">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-ink text-paper"><Logo size={20} /></span>
            <span className="font-display text-2xl font-extrabold">Reja<span className="text-accent">.</span></span>
          </div>
          <label className="ml-auto flex items-center gap-2 text-sm">
            <span className="sr-only">Til / Language</span>
            <select value={lang} onChange={(e) => setLang(e.target.value as Lang)} className="field h-10 w-auto py-0">
              {LANGS.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
            </select>
          </label>
        </div>

        <div>
          <h1 className="font-display text-4xl font-extrabold tracking-tight">{mode === "login" ? t("auth.login") : t("auth.register")}</h1>
          <p className="mt-2 text-ink-3">{t("app.tagline")}</p>
        </div>

        <div role="tablist" className="flex rounded-xl bg-paper-3 p-1">
          {(["login", "register"] as const).map((m) => (
            <button
              key={m}
              role="tab"
              type="button"
              aria-selected={mode === m}
              onClick={() => { setMode(m); setError(null); }}
              className={`h-10 flex-1 rounded-lg text-sm font-bold ${mode === m ? "bg-surface shadow-sm" : "text-ink-3"}`}
            >
              {m === "login" ? t("auth.login") : t("auth.register")}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
          {mode === "register" && (
            <label className="flex flex-col gap-1.5">
              <span className="label">{t("auth.name")}</span>
              <input className="field" value={name} onChange={(e) => setName(e.target.value)} required maxLength={80} autoComplete="name" />
            </label>
          )}
          <label className="flex flex-col gap-1.5">
            <span className="label">{t("auth.email")}</span>
            <input className="field" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" inputMode="email" />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="label">{t("auth.password")}</span>
            <input
              className="field"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={mode === "register" ? 8 : undefined}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
            />
            {mode === "register" && <span className="text-xs text-ink-muted">{t("auth.passwordHint")}</span>}
          </label>
          {needCode && mode === "login" && (
            <label className="flex flex-col gap-1.5">
              <span className="label">{t("auth.code")}</span>
              <input
                className="field font-mono tracking-widest"
                value={code}
                autoFocus
                autoComplete="one-time-code"
                inputMode="text"
                maxLength={20}
                onChange={(e) => setCode(e.target.value)}
              />
              <span className="text-xs text-ink-muted">{t("auth.codeHint")}</span>
            </label>
          )}
          {error && <p role="alert" className="rounded-lg bg-warn-soft px-3 py-2 text-sm font-semibold text-warn-ink">{error}</p>}
          <button
            className="btn-primary h-12 text-base"
            disabled={busy || !email || !password || (mode === "register" && (!name || password.length < 8)) || (needCode && !code.trim())}
          >
            {mode === "login" ? t("auth.submitLogin") : t("auth.submitRegister")}
          </button>
          {mode === "login" && (
            <Link href="/forgot" className="self-center text-sm font-semibold text-accent-ink underline underline-offset-2">{t("auth.forgot")}</Link>
          )}
        </form>
      </section>
    </main>
  );
}
