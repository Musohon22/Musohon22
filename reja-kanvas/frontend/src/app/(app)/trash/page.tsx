"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { loadPlans, online, restorePlan, toast, useT } from "@/lib/store";
import type { Plan } from "@/lib/types";
import { Restore, Trash } from "@/components/Icons";

export default function TrashPage() {
  const t = useT();
  const [plans, setPlans] = useState<Plan[] | null>(null);

  const load = useCallback(() => {
    api.get<{ plans: Plan[] }>("/api/trash").then((r) => setPlans(r.plans)).catch(() => setPlans((p) => p ?? []));
  }, []);
  useEffect(load, [load]);

  function restore(p: Plan) {
    restorePlan(p.id);
    setPlans((list) => list?.filter((x) => x.id !== p.id) ?? null);
    toast(t("trash.restored"), { tone: "success" });
    setTimeout(() => void loadPlans(), 800);
  }

  async function purge(p: Plan) {
    if (!window.confirm(t("trash.purgeConfirm"))) return;
    const ok = await online(async () => {
      await api.del(`/api/trash/${p.id}`);
      return true;
    });
    if (ok) setPlans((list) => list?.filter((x) => x.id !== p.id) ?? null);
  }

  const daysLeft = (iso?: string) => (iso ? Math.max(0, Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000)) : 30);

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-8 sm:px-6">
      <div>
        <h1 className="font-display text-3xl font-extrabold tracking-tight">{t("trash.title")}</h1>
        <p className="mt-1 text-ink-3">{t("trash.lead")}</p>
      </div>
      {plans === null && <p className="text-ink-muted">{t("common.loading")}</p>}
      {plans?.length === 0 && (
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-line-strong p-10 text-ink-muted">
          <Trash size={28} />
          {t("trash.empty")}
        </div>
      )}
      <ul className="flex flex-col gap-2">
        {plans?.map((p) => (
          <li key={p.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-white p-3">
            <div className="min-w-0 flex-1 basis-56">
              <div className="truncate font-semibold">{p.title}</div>
              <div className={`text-xs ${daysLeft(p.purge_at) <= 3 ? "font-bold text-warn-strong" : "text-ink-muted"}`}>{t("trash.daysLeft", { n: daysLeft(p.purge_at) })}</div>
            </div>
            <button type="button" className="btn h-10" onClick={() => restore(p)}><Restore size={16} />{t("trash.restore")}</button>
            <button type="button" className="btn-danger h-10" onClick={() => void purge(p)}>{t("trash.purge")}</button>
          </li>
        ))}
      </ul>
    </main>
  );
}
