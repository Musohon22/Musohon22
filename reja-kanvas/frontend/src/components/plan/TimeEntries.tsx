"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { loadDetail, online, useStore, useT } from "@/lib/store";
import { durationParts, fmtDateTime, fromLocalInput, toLocalInput } from "@/lib/time";
import type { TimeEntry } from "@/lib/types";
import { X } from "../Icons";

export function TimeEntries({ planId, editable }: { planId: string; editable: boolean }) {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState(() => toLocalInput(new Date(Date.now() - 3600_000).toISOString(), user.tz));
  const [minutes, setMinutes] = useState(30);
  const [note, setNote] = useState("");

  const load = useCallback(() => {
    api.get<{ entries: TimeEntry[] }>(`/api/plans/${planId}/time-entries`).then((r) => setEntries(r.entries)).catch(() => undefined);
  }, [planId]);
  useEffect(load, [load]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const started_at = fromLocalInput(start, user.tz);
    const r = await online(() => api.post<{ entries: TimeEntry[] }>(`/api/plans/${planId}/time-entries`, { started_at, minutes, note: note.trim() }));
    if (r) {
      setEntries(r.entries);
      setNote("");
      setOpen(false);
      void loadDetail(planId);
    }
  }

  async function remove(id: number) {
    const r = await online(() => api.del<{ entries: TimeEntry[] }>(`/api/time-entries/${id}`));
    if (r) {
      setEntries(r.entries);
      void loadDetail(planId);
    }
  }

  const dur = (s: number) => {
    const p = durationParts(s / 60);
    return t(`common.${p.unit}`, { n: p.n });
  };

  return (
    <div className="flex flex-col gap-2">
      <h3 className="label">{t("time.entries")}</h3>
      {entries.length === 0 && <p className="text-xs text-ink-muted">{t("time.none")}</p>}
      <ul className="flex max-h-48 flex-col gap-1 overflow-y-auto">
        {entries.map((e) => (
          <li key={e.id} className="flex items-center gap-2 text-sm">
            <span className="font-mono text-xs text-ink-muted">{fmtDateTime(e.started_at, user.tz, lang)}</span>
            <span className="font-semibold">{dur(e.seconds)}</span>
            {e.manual ? <span className="text-xs text-ink-muted">· {t("time.manual")}</span> : null}
            <span className="min-w-0 flex-1 truncate text-xs text-ink-3">{e.note}</span>
            {editable && (
              <button type="button" aria-label={t("time.delete")} className="btn-icon h-8 w-8" onClick={() => void remove(e.id)}>
                <X size={14} />
              </button>
            )}
          </li>
        ))}
      </ul>
      {editable &&
        (open ? (
          <form onSubmit={add} className="grid grid-cols-2 gap-2">
            <label className="col-span-2 flex flex-col gap-1">
              <span className="label">{t("time.start")}</span>
              <input type="datetime-local" className="field" value={start} onChange={(e) => setStart(e.target.value)} required />
            </label>
            <label className="flex flex-col gap-1">
              <span className="label">{t("time.minutes")}</span>
              <input type="number" min={1} max={1440} className="field" value={minutes} onChange={(e) => setMinutes(Math.max(1, Number(e.target.value) || 1))} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="label">{t("time.note")}</span>
              <input className="field" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
            </label>
            <div className="col-span-2 flex gap-2">
              <button className="btn-dark flex-1">{t("common.save")}</button>
              <button type="button" className="btn" onClick={() => setOpen(false)}>{t("common.cancel")}</button>
            </div>
          </form>
        ) : (
          <button type="button" className="self-start text-sm font-semibold text-accent-ink underline underline-offset-2" onClick={() => setOpen(true)}>
            {t("time.add")}
          </button>
        ))}
    </div>
  );
}
