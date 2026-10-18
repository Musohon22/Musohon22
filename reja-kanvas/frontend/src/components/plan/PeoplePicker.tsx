"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { errorText, useStore, useT } from "@/lib/store";
import type { Person } from "@/lib/types";
import { X } from "../Icons";

/** Choose a colleague by email. Lookups need the server, so this is disabled offline. */
export function PeoplePicker({
  label, person, disabled, onChange, hint,
}: {
  label: string;
  person: Person | null;
  disabled: boolean;
  onChange: (p: Person | null) => void;
  hint?: string;
}) {
  const t = useT();
  const reachable = useStore((s) => s.online && !s.serverDown);
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function find(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const p = await api.get<Person>(`/api/users/lookup?email=${encodeURIComponent(email.trim())}`);
      onChange(p);
      setEmail("");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <span className="label">{label}</span>
      {person ? (
        <div className="flex h-11 items-center gap-2 rounded-xl border border-line bg-surface pl-2 pr-1">
          <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-[#9FC3FF] text-xs font-extrabold text-[#0E2A66]">
            {person.name.slice(0, 1).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1 truncate text-sm">
            <b>{person.name}</b> <span className="text-ink-muted">{person.email}</span>
          </span>
          {!disabled && (
            <button type="button" aria-label={`${t("people.remove")}: ${person.name}`} className="btn-icon h-9 w-9" onClick={() => onChange(null)}>
              <X size={16} />
            </button>
          )}
        </div>
      ) : (
        <form onSubmit={find} className="flex gap-1.5">
          <label className="flex-1">
            <span className="sr-only">{label}</span>
            <input
              type="email"
              className="field"
              value={email}
              disabled={disabled || !reachable}
              placeholder={reachable ? t("people.placeholder") : t("err.offline_action")}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <button className="btn" disabled={disabled || !reachable || busy || !email.trim()}>{t("people.find")}</button>
        </form>
      )}
      {error && <span role="alert" className="text-xs font-semibold text-warn-strong">{error}</span>}
      {hint && <span className="text-xs text-ink-muted">{hint}</span>}
    </div>
  );
}
