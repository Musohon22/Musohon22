"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { online, useStore, useT } from "@/lib/store";
import { fmtDateTime, minutesSince } from "@/lib/time";
import type { Comment } from "@/lib/types";

/** Discussion between the owner and approvers. @email mentions notify that person. */
const EMOJI = ["👍", "❤️", "🎉", "✅", "👀", "🙏"];

export function Comments({ planId }: { planId: string }) {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const [items, setItems] = useState<Comment[] | null>(null);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.get<{ comments: Comment[] }>(`/api/plans/${planId}/comments`).then((r) => setItems(r.comments)).catch(() => setItems((c) => c ?? []));
  }, [planId]);
  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const body = draft.trim();
    if (!body) return;
    setBusy(true);
    const c = await online(() => api.post<Comment>(`/api/plans/${planId}/comments`, { body }));
    setBusy(false);
    if (c) {
      setItems((list) => [...(list ?? []), c]);
      setDraft("");
    }
  }

  async function saveEdit(id: string) {
    const c = await online(() => api.patch<Comment>(`/api/comments/${id}`, { body: editText.trim() }));
    if (c) setItems((list) => list?.map((x) => (x.id === id ? c : x)) ?? null);
    setEditing(null);
  }

  async function react(id: string, emoji: string) {
    const r = await online(() => api.post<{ reactions: Comment["reactions"] }>(`/api/comments/${id}/reactions`, { emoji }));
    if (r) setItems((list) => list?.map((x) => (x.id === id ? { ...x, reactions: r.reactions } : x)) ?? null);
  }

  async function remove(id: string) {
    const ok = await online(async () => {
      await api.del(`/api/comments/${id}`);
      return true;
    });
    if (ok) setItems((list) => list?.filter((x) => x.id !== id) ?? null);
  }

  return (
    <section aria-labelledby="comments-title" className="flex flex-col gap-3 border-t border-dashed border-line-strong pt-5">
      <h2 id="comments-title" className="eyebrow">{t("comments.title")}</h2>
      {items?.length === 0 && <p className="text-sm text-ink-muted">{t("comments.empty")}</p>}
      <ul className="flex flex-col gap-3">
        {items?.map((c) => {
          const mine = c.user_id === user.id;
          const canEdit = mine && minutesSince(c.created_at) < 15;
          return (
            <li key={c.id} className={`flex flex-col gap-1 rounded-xl p-3 ${mine ? "bg-accent-soft/60" : "bg-surface"}`}>
              <div className="flex items-center gap-2 text-xs text-ink-muted">
                <b className="text-ink-2">{c.user_name ?? "—"}</b>
                <span>{fmtDateTime(c.created_at, user.tz, lang)}</span>
                {c.edited_at && <span>· {t("comments.edited")}</span>}
              </div>
              {editing === c.id ? (
                <form onSubmit={(e) => { e.preventDefault(); void saveEdit(c.id); }} className="flex flex-col gap-2">
                  <label>
                    <span className="sr-only">{t("comments.edit")}</span>
                    <textarea className="field h-auto py-2" rows={2} maxLength={2000} value={editText} onChange={(e) => setEditText(e.target.value)} />
                  </label>
                  <div className="flex gap-2">
                    <button className="btn-primary h-9 px-3" disabled={!editText.trim()}>{t("comments.save")}</button>
                    <button type="button" className="btn h-9 px-3" onClick={() => setEditing(null)}>{t("common.cancel")}</button>
                  </div>
                </form>
              ) : (
                <p className="whitespace-pre-wrap break-words text-sm text-ink">{c.body}</p>
              )}
              <div className="flex flex-wrap items-center gap-1">
                {(c.reactions ?? []).map((r) => (
                  <button
                    key={r.emoji}
                    type="button"
                    aria-pressed={r.mine}
                    onClick={() => void react(c.id, r.emoji)}
                    className={`flex h-7 items-center gap-1 rounded-full border px-2 text-xs ${r.mine ? "border-accent bg-accent-soft" : "border-line bg-surface"}`}
                  >
                    <span aria-hidden="true">{r.emoji}</span>
                    <span className="font-semibold">{r.count}</span>
                  </button>
                ))}
                <details className="relative">
                  <summary aria-label="+" className="flex h-7 w-7 cursor-pointer list-none items-center justify-center rounded-full text-sm text-ink-muted hover:bg-paper-3 [&::-webkit-details-marker]:hidden">☺</summary>
                  <div className="absolute left-0 z-20 mt-1 flex gap-1 rounded-xl border border-line bg-surface p-1 shadow-lift">
                    {EMOJI.map((e) => (
                      <button
                        key={e}
                        type="button"
                        className="h-8 w-8 rounded-lg text-base hover:bg-paper-2"
                        onClick={(ev) => {
                          (ev.currentTarget.closest("details") as HTMLDetailsElement).removeAttribute("open");
                          void react(c.id, e);
                        }}
                      >
                        {e}
                      </button>
                    ))}
                  </div>
                </details>
              </div>
              {mine && editing !== c.id && (
                <div className="flex gap-3 text-xs font-semibold">
                  {canEdit && <button type="button" className="text-accent-ink" onClick={() => { setEditing(c.id); setEditText(c.body); }}>{t("comments.edit")}</button>}
                  <button type="button" className="text-warn-strong" onClick={() => void remove(c.id)}>{t("comments.delete")}</button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <form onSubmit={send} className="flex flex-col gap-2">
        <label>
          <span className="sr-only">{t("comments.placeholder")}</span>
          <textarea
            className="field h-auto py-2.5"
            rows={2}
            maxLength={2000}
            value={draft}
            placeholder={t("comments.placeholder")}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void send(e);
            }}
          />
        </label>
        <button className="btn-dark self-end" disabled={busy || !draft.trim()}>{t("comments.send")}</button>
      </form>
    </section>
  );
}
