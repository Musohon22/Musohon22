"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { online, toast, useStore, useT } from "@/lib/store";
import { fmtDate } from "@/lib/time";
import type { ShareLink } from "@/lib/types";
import { Dialog } from "../Dialog";
import { Copy } from "../Icons";

export function ShareDialog({ planId, open, onClose }: { planId: string; open: boolean; onClose: () => void }) {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const [links, setLinks] = useState<ShareLink[]>([]);
  const [role, setRole] = useState<"view" | "edit">("view");
  const [days, setDays] = useState(7);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    void online(() => api.get<{ shares: ShareLink[] }>(`/api/plans/${planId}/shares`)).then((r) => r && setLinks(r.shares));
  }, [open, planId]);

  const urlOf = (token: string) => `${window.location.origin}/s/${token}`;

  async function copy(token: string) {
    try {
      await navigator.clipboard.writeText(urlOf(token));
      toast(t("share.copied"), { tone: "success" });
    } catch {
      window.prompt(t("share.copy"), urlOf(token));
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const link = await online(() => api.post<ShareLink>(`/api/plans/${planId}/shares`, { role, expires_in_days: days }));
    setBusy(false);
    if (link) {
      setLinks((l) => [link, ...l]);
      void copy(link.token);
    }
  }

  async function revoke(token: string) {
    const ok = await online(async () => {
      await api.del(`/api/shares/${token}`);
      return true;
    });
    if (ok) setLinks((l) => l.map((x) => (x.token === token ? { ...x, revoked_at: new Date().toISOString() } : x)));
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("share.title")}>
      <form onSubmit={create} className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="label">{t("share.role")}</span>
            <select className="field" value={role} onChange={(e) => setRole(e.target.value as "view" | "edit")}>
              <option value="view">{t("share.view")}</option>
              <option value="edit">{t("share.edit")}</option>
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="label">{t("share.expires")}</span>
            <select className="field" value={days} onChange={(e) => setDays(Number(e.target.value))}>
              {[1, 7, 30, 90].map((d) => <option key={d} value={d}>{t("share.days", { n: d })}</option>)}
            </select>
          </label>
        </div>
        <p className="rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn-ink">{t("share.warning")}</p>
        <button className="btn-primary" disabled={busy}>{t("share.create")}</button>
      </form>

      <ul className="flex flex-col gap-2">
        {links.length === 0 && <li className="text-sm text-ink-muted">{t("share.none")}</li>}
        {links.map((l) => {
          const expired = new Date(l.expires_at) < new Date();
          const dead = !!l.revoked_at || expired;
          return (
            <li key={l.token} className={`flex items-center gap-2 rounded-xl border border-line bg-white p-2.5 ${dead ? "opacity-60" : ""}`}>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-bold">{l.role === "edit" ? t("share.edit") : t("share.view")}</div>
                <div className="text-xs text-ink-muted">
                  {l.revoked_at ? t("share.revoked") : expired ? t("share.expired") : t("share.until", { date: fmtDate(l.expires_at, user.tz, lang) })}
                </div>
              </div>
              {!dead && (
                <>
                  <button type="button" className="btn h-9 px-3" onClick={() => void copy(l.token)}><Copy size={15} />{t("share.copy")}</button>
                  <button type="button" className="btn-danger h-9 px-3" onClick={() => void revoke(l.token)}>{t("share.revoke")}</button>
                </>
              )}
            </li>
          );
        })}
      </ul>
    </Dialog>
  );
}
