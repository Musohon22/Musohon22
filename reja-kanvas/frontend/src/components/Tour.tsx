"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { setUser, useStore, useT } from "@/lib/store";
import type { MessageKey } from "@/lib/i18n";
import type { Prefs } from "@/lib/types";
import { Dialog } from "./Dialog";

const STEPS = [1, 2, 3, 4] as const;
export const REPLAY_TOUR = "reja:tour";

/** A four-step welcome shown once per account (and on demand from Settings). */
export function Tour() {
  const t = useT();
  const user = useStore((s) => s.user);
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (user && user.prefs && !user.prefs.onboarded) setOpen(true);
    const replay = () => {
      setStep(0);
      setOpen(true);
    };
    window.addEventListener(REPLAY_TOUR, replay);
    return () => window.removeEventListener(REPLAY_TOUR, replay);
  }, [user]);

  async function finish() {
    setOpen(false);
    if (!user || user.prefs?.onboarded) return;
    const prefs = { ...(user.prefs ?? {}), onboarded: true } as Prefs;
    setUser({ ...user, prefs });
    try {
      await api.put("/api/me/prefs", prefs);
    } catch {
      /* shown again next time; harmless */
    }
  }

  if (!user) return null;
  const n = STEPS[step];
  return (
    <Dialog open={open} onClose={() => void finish()} title={t(`tour.t${n}` as MessageKey)}>
      <p className="text-ink-2">{t(`tour.b${n}` as MessageKey)}</p>
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm text-ink-muted">{t("tour.step", { n: step + 1, total: STEPS.length })}</span>
        <div className="flex gap-2">
          {step < STEPS.length - 1 && <button type="button" className="btn" onClick={() => void finish()}>{t("tour.skip")}</button>}
          <button type="button" className="btn-primary" onClick={() => (step < STEPS.length - 1 ? setStep(step + 1) : void finish())}>
            {step < STEPS.length - 1 ? t("tour.next") : t("tour.done")}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
