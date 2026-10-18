"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { freeSlot } from "@/lib/canvas";
import { describeRecurrence } from "@/lib/recurrence";
import { normalize } from "@/lib/search";
import { createPlan, toast, useStore, useT } from "@/lib/store";
import { fmtDateTime } from "@/lib/time";
import { toggleTheme } from "@/lib/theme";
import type { MessageKey } from "@/lib/i18n";
import type { ParsedPlan } from "@/lib/types";
import { Calendar, Card, Grid, Inbox, ListIcon, Plus, Search, Settings, Target, Trash } from "./Icons";

interface Item {
  id: string;
  label: string;
  hint?: string;
  icon: React.ReactNode;
  run: () => void;
  group: "create" | "plans" | "commands";
}

const NAV: { href: string; key: MessageKey; icon: React.ReactNode }[] = [
  { href: "/canvas", key: "nav.canvas", icon: <Grid size={16} /> },
  { href: "/list", key: "nav.list", icon: <ListIcon size={16} /> },
  { href: "/calendar", key: "nav.calendar", icon: <Calendar size={16} /> },
  { href: "/analytics", key: "nav.analytics", icon: <Target size={16} /> },
  { href: "/inbox", key: "nav.inbox", icon: <Inbox size={16} /> },
  { href: "/trash", key: "nav.trash", icon: <Trash size={16} /> },
  { href: "/settings", key: "nav.settings", icon: <Settings size={16} /> },
];

/** Ctrl/Cmd+K: type a plan in plain words to create it, find any plan, or jump anywhere. */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT();
  const router = useRouter();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const planMap = useStore((s) => s.plans);
  const reachable = useStore((s) => s.online && !s.serverDown);
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<ParsedPlan | null>(null);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const el = dialog.current;
    if (!el) return;
    if (open && !el.open) {
      el.showModal();
      setText("");
      setParsed(null);
      setActive(0);
      setTimeout(() => input.current?.focus(), 0);
    }
    if (!open && el.open) el.close();
  }, [open]);

  // Server-side parsing understands dates in three languages; offline the text is the title.
  useEffect(() => {
    const value = text.trim();
    if (!value || !reachable) {
      setParsed(null);
      return;
    }
    const id = setTimeout(() => {
      api.post<ParsedPlan>("/api/parse", { text: value }).then(setParsed).catch(() => setParsed(null));
    }, 250);
    return () => clearTimeout(id);
  }, [text, reachable]);

  function go(href: string) {
    onClose();
    router.push(href);
  }

  function create() {
    const value = text.trim();
    if (!value) return;
    const p = parsed && parsed.title ? parsed : null;
    const plans = Object.values(planMap);
    const pos = freeSlot(plans, {});
    const id = createPlan({
      title: (p?.title ?? value).slice(0, 200),
      x: pos.x,
      y: pos.y,
      due_at: p?.due_at ?? null,
      tag: p?.tag ?? null,
      priority: p?.priority ?? "normal",
      recurrence: p?.recurrence ?? null,
    });
    onClose();
    toast(t("palette.created"), { tone: "success", action: { label: t("card.open"), run: () => router.push(`/plan/${id}`) } });
  }

  const items = useMemo<Item[]>(() => {
    const q = normalize(text);
    const out: Item[] = [];
    if (text.trim()) {
      out.push({ id: "create", group: "create", icon: <Plus size={16} />, label: parsed?.title || text.trim(), hint: t("palette.create"), run: create });
    }
    if (q) {
      Object.values(planMap)
        .filter((p) => normalize(`${p.title} ${p.tag ?? ""}`).includes(q))
        .slice(0, 6)
        .forEach((p) => out.push({ id: p.id, group: "plans", icon: <Card size={16} />, label: p.title, hint: p.tag ?? undefined, run: () => go(`/plan/${p.id}`) }));
    }
    const commands: Item[] = [
      ...NAV.map((n) => ({ id: n.href, group: "commands" as const, icon: n.icon, label: t(n.key), run: () => go(n.href) })),
      { id: "theme", group: "commands", icon: <Target size={16} />, label: t("palette.toggleTheme"), run: () => { toggleTheme(); onClose(); } },
    ];
    out.push(...commands.filter((c) => !q || normalize(c.label).includes(q)));
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, parsed, planMap, t]);

  useEffect(() => setActive(0), [text]);

  const chips: string[] = [];
  if (parsed?.due_at) chips.push(fmtDateTime(parsed.due_at, user.tz, lang));
  if (parsed?.tag) chips.push(`#${parsed.tag}`);
  if (parsed?.priority && parsed.priority !== "normal") chips.push(t(`priority.${parsed.priority}`));
  if (parsed?.recurrence) chips.push(describeRecurrence(parsed.recurrence, t));

  return (
    <dialog
      ref={dialog}
      aria-label={t("palette.label")}
      onCancel={(e) => { e.preventDefault(); onClose(); }}
      onClick={(e) => e.target === dialog.current && onClose()}
      className="mx-auto mt-[12vh] w-[calc(100%-24px)] max-w-xl rounded-2xl border border-line bg-paper-2 p-0 text-ink shadow-lift backdrop:bg-ink/40"
    >
      {open && (
        <div className="flex flex-col">
          <label className="flex items-center gap-3 border-b border-line px-4">
            <Search size={18} className="text-ink-muted" />
            <span className="sr-only">{t("palette.placeholder")}</span>
            <input
              ref={input}
              role="combobox"
              aria-expanded
              aria-controls="palette-list"
              aria-activedescendant={items[active] ? `pi-${items[active].id}` : undefined}
              value={text}
              maxLength={300}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
                if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
                if (e.key === "Enter") { e.preventDefault(); items[active]?.run(); }
              }}
              placeholder={t("palette.placeholder")}
              className="h-14 min-w-0 flex-1 bg-transparent text-[16px] outline-none placeholder:text-ink-muted"
            />
          </label>
          {chips.length > 0 && (
            <div className="flex flex-wrap gap-1.5 border-b border-line-soft px-4 py-2">
              {chips.map((c) => <span key={c} className="chip bg-accent-soft text-accent-ink">{c}</span>)}
            </div>
          )}
          <ul id="palette-list" role="listbox" className="max-h-[50vh] overflow-y-auto p-2">
            {items.map((item, i) => {
              const header = i === 0 || items[i - 1].group !== item.group;
              return (
                <li key={item.id} role="none">
                  {header && item.group !== "create" && (
                    <div className="px-3 pb-1 pt-3 text-[11px] font-bold uppercase tracking-[0.08em] text-ink-muted">
                      {item.group === "plans" ? t("palette.plans") : t("palette.commands")}
                    </div>
                  )}
                  <div
                    id={`pi-${item.id}`}
                    role="option"
                    aria-selected={i === active}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => item.run()}
                    className={`flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-sm ${i === active ? "bg-accent-soft text-ink" : ""}`}
                  >
                    <span className="text-ink-muted">{item.icon}</span>
                    <span className="min-w-0 flex-1 truncate font-semibold">{item.label}</span>
                    {item.hint && <span className="text-xs text-ink-muted">{item.hint}</span>}
                  </div>
                </li>
              );
            })}
          </ul>
          <div className="border-t border-line-soft px-4 py-2 text-xs text-ink-muted">{t("palette.hint")}</div>
        </div>
      )}
    </dialog>
  );
}
