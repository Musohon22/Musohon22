"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { errorText, useT } from "@/lib/store";
import { AuthCard } from "@/components/AuthCard";

export default function ResetPage() {
  const t = useT();
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setToken(new URLSearchParams(window.location.search).get("token") ?? "");
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.post("/api/auth/reset", { token, password }, { auth: false });
      setDone(true);
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <AuthCard title={t("auth.resetTitle")}>
      {done ? (
        <p role="status" className="rounded-xl bg-ok-soft p-4 text-ok-ink">{t("auth.resetDone")}</p>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5">
            <span className="label">{t("settings.newPassword")}</span>
            <input type="password" required minLength={8} autoComplete="new-password" className="field" value={password} onChange={(e) => setPassword(e.target.value)} />
            <span className="text-xs text-ink-muted">{t("auth.passwordHint")}</span>
          </label>
          {error && <p role="alert" className="text-sm font-semibold text-warn-strong">{error}</p>}
          <button className="btn-primary h-12" disabled={!token || password.length < 8}>{t("common.save")}</button>
        </form>
      )}
      <Link href="/login" className="text-sm font-semibold text-accent-ink underline underline-offset-2">{t("auth.backToLogin")}</Link>
    </AuthCard>
  );
}
