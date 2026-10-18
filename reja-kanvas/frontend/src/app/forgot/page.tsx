"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { errorText, useT } from "@/lib/store";
import { AuthCard } from "@/components/AuthCard";

export default function ForgotPage() {
  const t = useT();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.post("/api/auth/forgot", { email }, { auth: false });
      setSent(true);
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <AuthCard title={t("auth.forgotTitle")}>
      {sent ? (
        <p role="status" className="rounded-xl bg-ok-soft p-4 text-ok-ink">{t("auth.forgotSent")}</p>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-4">
          <p className="text-ink-3">{t("auth.forgotLead")}</p>
          <label className="flex flex-col gap-1.5">
            <span className="label">{t("auth.email")}</span>
            <input type="email" required autoComplete="email" className="field" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          {error && <p role="alert" className="text-sm font-semibold text-warn-strong">{error}</p>}
          <button className="btn-primary h-12" disabled={!email}>{t("auth.forgotSend")}</button>
        </form>
      )}
      <Link href="/login" className="text-sm font-semibold text-accent-ink underline underline-offset-2">{t("auth.backToLogin")}</Link>
    </AuthCard>
  );
}
