"use client";

import { memo, useRef, useState } from "react";
import { snap } from "@/lib/canvas";
import { useT } from "@/lib/store";
import type { CanvasItem } from "@/lib/types";
import { CARD_BG } from "./PlanCard";
import { X } from "../Icons";

interface Props {
  item: CanvasItem;
  zoom: number;
  readOnly: boolean;
  onCommit: (item: CanvasItem) => void;
  onDelete: (id: string) => void;
}

/** A free note or a group frame on the canvas. Handles its own drag and resize. */
function CanvasItemInner({ item, zoom, readOnly, onCommit, onDelete }: Props) {
  const t = useT();
  const [live, setLive] = useState<CanvasItem | null>(null);
  const [editing, setEditing] = useState(false);
  const start = useRef<{ x: number; y: number; it: CanvasItem; mode: "move" | "resize" } | null>(null);
  const shown = live ?? item;

  const down = (mode: "move" | "resize") => (e: React.PointerEvent) => {
    if (readOnly || editing || e.button !== 0) return;
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    start.current = { x: e.clientX, y: e.clientY, it: item, mode };
  };
  const move = (e: React.PointerEvent) => {
    const s = start.current;
    if (!s) return;
    e.stopPropagation();
    const dx = (e.clientX - s.x) / zoom;
    const dy = (e.clientY - s.y) / zoom;
    setLive(
      s.mode === "move"
        ? { ...s.it, x: s.it.x + dx, y: s.it.y + dy }
        : { ...s.it, w: Math.max(120, s.it.w + dx), h: Math.max(80, s.it.h + dy) },
    );
  };
  const up = (e: React.PointerEvent) => {
    const s = start.current;
    start.current = null;
    if (!s) return;
    e.stopPropagation();
    if (live) onCommit({ ...live, x: snap(live.x), y: snap(live.y), w: snap(live.w), h: snap(live.h) });
    setLive(null);
  };

  const keys = (e: React.KeyboardEvent) => {
    if (readOnly || editing || e.target !== e.currentTarget) return;
    const step = e.shiftKey ? 100 : 20;
    const d: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (d[e.key]) {
      e.preventDefault();
      onCommit({ ...item, x: item.x + d[e.key][0], y: item.y + d[e.key][1] });
    } else if (e.key === "Delete") onDelete(item.id);
    else if (e.key === "Enter") setEditing(true);
  };

  const text = editing ? (
    <textarea
      autoFocus
      aria-label={item.kind === "note" ? t("canvas.noteText") : t("canvas.frameTitle")}
      defaultValue={item.text}
      maxLength={2000}
      onPointerDown={(e) => e.stopPropagation()}
      onBlur={(e) => {
        setEditing(false);
        if (e.target.value !== item.text) onCommit({ ...item, text: e.target.value });
      }}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Escape") (e.target as HTMLTextAreaElement).blur();
      }}
      className="h-full w-full resize-none bg-transparent text-[15px] leading-snug outline-none"
    />
  ) : (
    <div className="h-full w-full overflow-hidden whitespace-pre-wrap break-words text-[15px] leading-snug">{item.text}</div>
  );

  const handle = !readOnly && (
    <span
      role="presentation"
      title={t("canvas.resize")}
      onPointerDown={down("resize")}
      onPointerMove={move}
      onPointerUp={up}
      className="absolute bottom-1 right-1 h-4 w-4 cursor-nwse-resize rounded-sm border-b-2 border-r-2 border-ink-muted/60"
    />
  );
  const del = !readOnly && (
    <button
      type="button"
      aria-label={t("canvas.deleteItem")}
      onPointerDown={(e) => e.stopPropagation()}
      onClick={() => onDelete(item.id)}
      className="absolute -right-3 -top-3 hidden h-7 w-7 items-center justify-center rounded-full bg-ink text-paper group-hover:flex group-focus-within:flex"
    >
      <X size={12} />
    </button>
  );

  if (item.kind === "frame") {
    return (
      <div className="group pointer-events-none absolute" style={{ left: shown.x, top: shown.y, width: shown.w, height: shown.h }}>
        <div className="absolute inset-0 rounded-[26px] border-2 border-dashed border-ink-muted/40 bg-ink/[0.025]" />
        <div
          tabIndex={0}
          aria-label={item.text || t("canvas.frame")}
          onKeyDown={keys}
          onPointerDown={down("move")}
          onPointerMove={move}
          onPointerUp={up}
          onDoubleClick={() => !readOnly && setEditing(true)}
          className="pointer-events-auto absolute -top-9 left-3 flex h-8 min-w-24 max-w-[80%] cursor-grab items-center rounded-lg bg-paper-3 px-3 font-display text-sm font-bold text-ink-2"
        >
          {editing ? text : item.text || t("canvas.frame")}
        </div>
        <span className="pointer-events-auto">{handle}</span>
        <span className="pointer-events-auto">{del}</span>
      </div>
    );
  }

  return (
    <div
      tabIndex={0}
      aria-label={item.text || t("canvas.note")}
      onKeyDown={keys}
      onPointerDown={down("move")}
      onPointerMove={move}
      onPointerUp={up}
      onDoubleClick={() => !readOnly && setEditing(true)}
      className={`card-scope group absolute cursor-grab rounded-md p-3 text-ink shadow-card ${CARD_BG[item.color]}`}
      style={{ left: shown.x, top: shown.y, width: shown.w, height: shown.h, transform: "rotate(-1deg)", touchAction: "none" }}
    >
      {text}
      {handle}
      {del}
    </div>
  );
}

export const CanvasItemView = memo(CanvasItemInner);
