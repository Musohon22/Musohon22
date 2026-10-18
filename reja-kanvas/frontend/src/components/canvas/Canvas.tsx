"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  arrange, boundsOf, CARD_W, centerOn, clampZoom, fitView, freeSlot, snap, ZONE_TOP, ZONE_W, ZONES,
  type View,
} from "@/lib/canvas";
import { needsConfirmPanel, submitWithUndo } from "@/lib/actions";
import { createPlan, deletePlan, deletePlans, movePlan, movePlans, toast, updatePlan, useStore, useT } from "@/lib/store";
import { PRIORITIES } from "@/lib/recurrence";
import { CARD_BG } from "./PlanCard";
import { normalize } from "@/lib/search";
import type { Plan } from "@/lib/types";
import { Arrange, Card, Fit, Minus, Plus, Search, X } from "../Icons";
import { PlanCard } from "./PlanCard";
import { Minimap } from "./Minimap";
import { EmptyState } from "./EmptyState";

const VIEW_KEY = "reja.view";
const HINTS_KEY = "reja.hintsHidden";

type Gesture =
  | { kind: "pan"; pointerId: number; sx: number; sy: number; vx: number; vy: number; moved: boolean }
  | {
      kind: "press"; pointerId: number; id: string; touch: boolean; sx: number; sy: number;
      ox: number; oy: number; offX: number; offY: number; timer: ReturnType<typeof setTimeout> | null;
    }
  | { kind: "drag"; pointerId: number; id: string; ox: number; oy: number; offX: number; offY: number }
  | { kind: "pinch"; d0: number; z0: number; wx: number; wy: number };

interface Drag {
  id: string;
  x: number;
  y: number;
  ox: number;
  oy: number;
  /** Other selected cards moving along with this one (shift-click multi-select). */
  group?: { id: string; ox: number; oy: number }[];
}

function loadView(): View {
  try {
    const v = JSON.parse(localStorage.getItem(VIEW_KEY) ?? "null");
    if (v && typeof v.x === "number" && typeof v.zoom === "number") return { ...v, zoom: clampZoom(v.zoom) };
  } catch {
    /* ignore */
  }
  return { x: 24, y: 8, zoom: 1 };
}

export function Canvas({ plans }: { plans: Plan[] }) {
  const t = useT();
  const router = useRouter();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const loaded = useStore((s) => s.loaded);

  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 1000, h: 700 });
  const [view, setViewState] = useState<View>({ x: 24, y: 8, zoom: 1 });
  const viewRef = useRef(view);
  const [heights, setHeights] = useState<Record<string, number>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [drag, setDragState] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const setDrag = (d: Drag | null) => {
    dragRef.current = d;
    setDragState(d);
  };
  const [pulse, setPulse] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [hintsHidden, setHintsHidden] = useState(true);
  const gesture = useRef<Gesture | null>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const plansRef = useRef(plans);
  plansRef.current = plans;
  // Pointer capture retargets click/dblclick to the canvas, so double-tap is detected here.
  const lastTap = useRef<{ id: string; at: number } | null>(null);
  const [multi, setMultiState] = useState<string[]>([]);
  const multiRef = useRef<string[]>([]);
  const setMulti = (ids: string[]) => {
    multiRef.current = ids;
    setMultiState(ids);
  };
  const groupFor = (id: string) =>
    multiRef.current.includes(id) && multiRef.current.length > 1
      ? plansRef.current.filter((p) => multiRef.current.includes(p.id) && p.id !== id).map((p) => ({ id: p.id, ox: p.x, oy: p.y }))
      : undefined;

  const setView = useCallback((v: View | ((v: View) => View)) => {
    setViewState((prev) => {
      const next = typeof v === "function" ? v(prev) : v;
      viewRef.current = next;
      return next;
    });
  }, []);

  // restore view and tips preference
  useEffect(() => {
    setView(loadView());
    try {
      setHintsHidden(localStorage.getItem(HINTS_KEY) === "1");
    } catch {
      setHintsHidden(false);
    }
  }, [setView]);

  useEffect(() => {
    const id = setTimeout(() => {
      try {
        localStorage.setItem(VIEW_KEY, JSON.stringify(view));
      } catch {
        /* ignore */
      }
    }, 400);
    return () => clearTimeout(id);
  }, [view]);

  // viewport size
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setSize({ w: entry.contentRect.width, h: entry.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // card heights (for culling, tidy-up and overlap checks)
  const cardObserver = useRef<ResizeObserver | null>(null);
  const observed = useRef(new Map<string, HTMLElement>());
  useEffect(() => {
    cardObserver.current = new ResizeObserver((entries) => {
      setHeights((h) => {
        let next = h;
        for (const e of entries) {
          const id = (e.target as HTMLElement).dataset.plan;
          const height = Math.round((e.target as HTMLElement).offsetHeight);
          if (id && h[id] !== height) next = next === h ? { ...h, [id]: height } : { ...next, [id]: height };
        }
        return next;
      });
    });
    observed.current.forEach((el) => cardObserver.current!.observe(el));
    return () => cardObserver.current?.disconnect();
  }, []);
  const measure = useCallback((id: string, el: HTMLElement | null) => {
    const prev = observed.current.get(id);
    if (prev === el) return;
    if (prev) cardObserver.current?.unobserve(prev);
    if (el) {
      observed.current.set(id, el);
      cardObserver.current?.observe(el);
    } else observed.current.delete(id);
  }, []);

  // wheel: scroll pans, ctrl/cmd (and trackpad pinch) zooms around the cursor
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const v = viewRef.current;
      if (e.ctrlKey || e.metaKey) {
        const rect = el.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const zoom = clampZoom(v.zoom * Math.exp(-e.deltaY * 0.0015));
        const wx = (mx - v.x) / v.zoom;
        const wy = (my - v.y) / v.zoom;
        setView({ zoom, x: mx - wx * zoom, y: my - wy * zoom });
      } else {
        setView({ ...v, x: v.x - e.deltaX, y: v.y - e.deltaY });
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [setView]);

  // ?focus=<id> from the list view or a notification
  const focusedOnce = useRef(false);
  useEffect(() => {
    if (focusedOnce.current || !plans.length) return;
    const id = new URLSearchParams(window.location.search).get("focus");
    if (id && plans.some((p) => p.id === id)) {
      focusedOnce.current = true;
      flyTo(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plans]);

  const toWorld = (cx: number, cy: number) => {
    const rect = box.current!.getBoundingClientRect();
    const v = viewRef.current;
    return { x: (cx - rect.left - v.x) / v.zoom, y: (cy - rect.top - v.y) / v.zoom };
  };

  // ---- gestures ----------------------------------------------------------------------

  function startPinch() {
    const pts = Array.from(pointers.current.values());
    if (pts.length < 2) return;
    const [a, b] = pts;
    const mid = toWorld((a.x + b.x) / 2, (a.y + b.y) / 2);
    if (gesture.current?.kind === "press" && gesture.current.timer) clearTimeout(gesture.current.timer);
    gesture.current = { kind: "pinch", d0: Math.hypot(a.x - b.x, a.y - b.y) || 1, z0: viewRef.current.zoom, wx: mid.x, wy: mid.y };
    setDrag(null);
  }

  const onCardPointerDown = useCallback((e: React.PointerEvent, plan: Plan) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest("button, textarea, input, a")) return;
    e.stopPropagation();
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    box.current?.setPointerCapture(e.pointerId);
    if (pointers.current.size > 1) return startPinch();
    const w = toWorld(e.clientX, e.clientY);
    const touch = e.pointerType === "touch";
    const g: Gesture = {
      kind: "press", pointerId: e.pointerId, id: plan.id, touch, sx: e.clientX, sy: e.clientY,
      ox: plan.x, oy: plan.y, offX: w.x - plan.x, offY: w.y - plan.y, timer: null,
    };
    if (touch) {
      // Touch: a long press picks the card up; a quick swipe still pans the canvas.
      g.timer = setTimeout(() => {
        const cur = gesture.current;
        if (cur?.kind === "press" && cur.pointerId === g.pointerId) {
          gesture.current = { kind: "drag", pointerId: cur.pointerId, id: cur.id, ox: cur.ox, oy: cur.oy, offX: cur.offX, offY: cur.offY };
          setDrag({ id: cur.id, x: cur.ox, y: cur.oy, ox: cur.ox, oy: cur.oy, group: groupFor(cur.id) });
          setSelected(cur.id);
          navigator.vibrate?.(12);
        }
      }, 350);
    }
    gesture.current = g;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onPointerDown(e: React.PointerEvent) {
    if (e.button !== 0 && e.pointerType === "mouse") return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    box.current?.setPointerCapture(e.pointerId);
    if (pointers.current.size > 1) return startPinch();
    const v = viewRef.current;
    gesture.current = { kind: "pan", pointerId: e.pointerId, sx: e.clientX, sy: e.clientY, vx: v.x, vy: v.y, moved: false };
  }

  function onPointerMove(e: React.PointerEvent) {
    if (!pointers.current.has(e.pointerId)) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const g = gesture.current;
    if (!g) return;
    if (g.kind === "pinch") {
      const [a, b] = Array.from(pointers.current.values());
      if (!b) return;
      const rect = box.current!.getBoundingClientRect();
      const zoom = clampZoom(g.z0 * (Math.hypot(a.x - b.x, a.y - b.y) / g.d0));
      const mx = (a.x + b.x) / 2 - rect.left;
      const my = (a.y + b.y) / 2 - rect.top;
      setView({ zoom, x: mx - g.wx * zoom, y: my - g.wy * zoom });
      return;
    }
    if (g.pointerId !== e.pointerId) return;
    if (g.kind === "pan") {
      const dx = e.clientX - g.sx;
      const dy = e.clientY - g.sy;
      if (Math.abs(dx) + Math.abs(dy) > 3) g.moved = true;
      setView((v) => ({ ...v, x: g.vx + dx, y: g.vy + dy }));
      return;
    }
    if (g.kind === "press") {
      const dist = Math.hypot(e.clientX - g.sx, e.clientY - g.sy);
      if (g.touch && dist > 8) {
        if (g.timer) clearTimeout(g.timer);
        const v = viewRef.current;
        gesture.current = { kind: "pan", pointerId: g.pointerId, sx: g.sx, sy: g.sy, vx: v.x, vy: v.y, moved: true };
        return;
      }
      if (!g.touch && dist > 4) {
        gesture.current = { kind: "drag", pointerId: g.pointerId, id: g.id, ox: g.ox, oy: g.oy, offX: g.offX, offY: g.offY };
        setSelected(g.id);
      } else return;
    }
    const d = gesture.current;
    if (d?.kind === "drag") {
      const w = toWorld(e.clientX, e.clientY);
      const group = dragRef.current?.id === d.id ? dragRef.current.group : groupFor(d.id);
      setDrag({ id: d.id, x: w.x - d.offX, y: w.y - d.offY, ox: d.ox, oy: d.oy, group });
    }
  }

  function onPointerUp(e: React.PointerEvent) {
    pointers.current.delete(e.pointerId);
    const g = gesture.current;
    if (!g) return;
    if (g.kind === "pinch") {
      if (pointers.current.size === 0) gesture.current = null;
      return;
    }
    if (g.pointerId !== e.pointerId) return;
    gesture.current = null;
    if (g.kind === "press") {
      if (g.timer) clearTimeout(g.timer);
      if (e.shiftKey || e.ctrlKey || e.metaKey) {
        const cur = multiRef.current;
        const base = cur.length ? cur : selected && selected !== g.id ? [selected] : [];
        setMulti(base.includes(g.id) ? base.filter((x) => x !== g.id) : [...base, g.id]);
        return;
      }
      if (!multiRef.current.includes(g.id)) setMulti([]);
      setSelected(g.id);
      const now = performance.now();
      if (lastTap.current?.id === g.id && now - lastTap.current.at < 400) {
        lastTap.current = null;
        const plan = plansRef.current.find((p) => p.id === g.id);
        if (plan && e.type === "pointerup") open(plan);
      } else lastTap.current = { id: g.id, at: now };
    } else if (g.kind === "pan") {
      if (!g.moved && e.type === "pointerup") {
        setSelected(null);
        setEditing(null);
        setMulti([]);
      }
    } else if (g.kind === "drag") {
      const cur = dragRef.current;
      if (cur && e.type === "pointerup") {
        const x = snap(cur.x);
        const y = snap(cur.y);
        if (x !== cur.ox || y !== cur.oy) {
          const dx = x - cur.ox;
          const dy = y - cur.oy;
          movePlans([{ id: cur.id, x, y }, ...(cur.group ?? []).map((m) => ({ id: m.id, x: m.ox + dx, y: m.oy + dy }))]);
        }
      }
      setDrag(null);
    }
  }

  // ---- actions -------------------------------------------------------------------------

  const open = useCallback((plan: Plan) => router.push(`/plan/${plan.id}`), [router]);

  const quickDone = useCallback(
    (plan: Plan) => {
      if (needsConfirmPanel(plan)) router.push(`/plan/${plan.id}#confirm`);
      else void submitWithUndo(plan.id);
    },
    [router],
  );

  const remove = useCallback((plan: Plan) => {
    setSelected(null);
    deletePlan(plan.id);
  }, []);

  const rename = useCallback((plan: Plan, title: string | null) => {
    setEditing(null);
    if (title && title !== plan.title) updatePlan(plan.id, { title });
  }, []);

  const onCardKey = useCallback(
    (e: React.KeyboardEvent, plan: Plan) => {
      if (e.target !== e.currentTarget) return;
      const step = e.shiftKey ? 100 : 20;
      const moves: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
      if (moves[e.key]) {
        e.preventDefault();
        movePlan(plan.id, snap(plan.x + moves[e.key][0]), snap(plan.y + moves[e.key][1]));
        setSelected(plan.id);
      } else if (e.key === "Enter") {
        e.preventDefault();
        open(plan);
      } else if (e.key === " ") {
        e.preventDefault();
        if (plan.status === "active" || plan.status === "returned") quickDone(plan);
      } else if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        remove(plan);
      } else if (e.key === "F2") {
        e.preventDefault();
        setEditing(plan.id);
      } else if (e.key === "Escape") {
        setSelected(null);
      }
    },
    [open, quickDone, remove],
  );

  const onCardFocus = (e: React.FocusEvent) => {
    const id = (e.target as HTMLElement).dataset?.plan;
    if (id) setSelected(id);
  };

  function animateTo(target: View) {
    const from = viewRef.current;
    const start = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / 320);
      const ease = 1 - Math.pow(1 - k, 3);
      setView({
        x: from.x + (target.x - from.x) * ease,
        y: from.y + (target.y - from.y) * ease,
        zoom: from.zoom + (target.zoom - from.zoom) * ease,
      });
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function flyTo(id: string) {
    const p = plansRef.current.find((x) => x.id === id);
    if (!p) return;
    const zoom = Math.max(viewRef.current.zoom, 0.9);
    animateTo(centerOn(p.x + CARD_W / 2, p.y + (heights[id] ?? 160) / 2, size.w, size.h, zoom));
    setSelected(id);
    setPulse(id);
    setTimeout(() => setPulse(null), 2200);
    setTimeout(() => (document.querySelector(`[data-plan="${id}"]`) as HTMLElement | null)?.focus({ preventScroll: true }), 350);
  }

  function fit() {
    const b = boundsOf(plans, heights);
    if (b) animateTo(fitView(b, size.w, size.h));
  }

  function zoomBy(f: number) {
    const v = viewRef.current;
    const zoom = clampZoom(v.zoom * f);
    const cx = size.w / 2;
    const cy = size.h / 2;
    animateTo({ zoom, x: cx - ((cx - v.x) / v.zoom) * zoom, y: cy - ((cy - v.y) / v.zoom) * zoom });
  }

  function tidy() {
    const moves = arrange(plans, user.tz, heights);
    if (moves.length) movePlans(moves);
    toast(t("canvas.arranged"), { tone: "success" });
    setTimeout(fit, 50);
  }

  function newCard() {
    const v = viewRef.current;
    const center = { x: (size.w / 2 - v.x) / v.zoom - CARD_W / 2, y: (size.h / 3 - v.y) / v.zoom };
    const pos = freeSlot(plans, heights, center);
    const id = createPlan({ title: t("canvas.newTitle"), x: pos.x, y: pos.y });
    setSelected(id);
    setEditing(id);
  }

  // ---- render --------------------------------------------------------------------------

  const results = useMemo(() => {
    const q = normalize(query);
    if (!q) return [];
    return plans.filter((p) => normalize(`${p.title} ${p.tag ?? ""}`).includes(q)).slice(0, 8);
  }, [query, plans]);

  const visible = useMemo(() => {
    const m = 300 / view.zoom;
    const x1 = -view.x / view.zoom - m;
    const y1 = -view.y / view.zoom - m;
    const x2 = (size.w - view.x) / view.zoom + m;
    const y2 = (size.h - view.y) / view.zoom + m;
    return plans.filter(
      (p) => p.id === selected || p.id === drag?.id || (p.x + CARD_W > x1 && p.x < x2 && p.y + (heights[p.id] ?? 200) > y1 && p.y < y2),
    );
  }, [plans, view, size, heights, selected, drag]);

  // Plans not finished yet; a card is "blocked" while any of its blockers is in here.
  const openIds = useMemo(() => new Set(plans.filter((p) => p.status !== "done" && p.status !== "cancelled").map((p) => p.id)), [plans]);
  const byId = useMemo(() => new Map(plans.map((p) => [p.id, p])), [plans]);
  const posOf = (p: Plan) => {
    if (!drag) return p;
    if (drag.id === p.id) return { x: drag.x, y: drag.y };
    const m = drag.group?.find((g) => g.id === p.id);
    return m ? { x: m.ox + drag.x - drag.ox, y: m.oy + drag.y - drag.oy } : p;
  };
  const links = plans.flatMap((p) =>
    p.blocked_by
      .map((b) => byId.get(b))
      .filter((b): b is Plan => !!b)
      .map((b) => {
        const from = posOf(b);
        const to = posOf(p);
        const x1 = from.x + CARD_W;
        const y1 = from.y + (heights[b.id] ?? 160) / 2;
        const x2 = to.x;
        const y2 = to.y + (heights[p.id] ?? 160) / 2;
        // leave from whichever side faces the target
        const forward = x2 >= x1 - 40;
        const sx = forward ? x1 : from.x;
        const ex = forward ? x2 : to.x + CARD_W;
        const bend = Math.max(60, Math.abs(ex - sx) / 2) * (forward ? 1 : -1);
        return { id: `${b.id}-${p.id}`, d: `M${sx},${y1} C${sx + bend},${y1} ${ex - bend},${y2} ${ex},${y2}`, open: openIds.has(b.id) };
      }),
  );

  const zoneHeight = Math.max(900, ...plans.map((p) => p.y + (heights[p.id] ?? 160) + 200));
  const lowDetail = view.zoom < 0.45;

  return (
    <div className="relative min-h-0 flex-1 overflow-hidden">
      <div
        ref={box}
        role="application"
        aria-label={t("canvas.label")}
        className="canvas-dots absolute inset-0 cursor-default overflow-hidden"
        style={{ touchAction: "none", backgroundSize: `${22 * view.zoom}px ${22 * view.zoom}px`, backgroundPosition: `${view.x}px ${view.y}px` }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onFocus={onCardFocus}
      >
        <div style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`, transformOrigin: "0 0", position: "absolute", left: 0, top: 0 }}>
          {ZONES.map((z, i) => (
            <div
              key={z.key}
              aria-hidden="true"
              className={`absolute rounded-[22px] ${i === 0 ? "border-[1.5px] border-line bg-surface/45" : "border-[1.5px] border-dashed border-line-strong bg-surface/30"}`}
              style={{ left: z.x, top: ZONE_TOP - 20, width: ZONE_W, height: zoneHeight }}
            >
              <div className="absolute left-5 top-3.5 flex items-center gap-2 font-display text-[15px] font-bold text-ink-2">
                {i === 0 && <span className="h-2 w-2 rounded-full bg-warn" />}
                {t(`zone.${z.key}`)}
              </div>
            </div>
          ))}

          {links.length > 0 && (
            <svg aria-hidden="true" className="pointer-events-none absolute left-0 top-0 overflow-visible" width={1} height={1}>
              <defs>
                <marker id="dep-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M0,0 L10,5 L0,10 z" className="fill-ink-muted" />
                </marker>
              </defs>
              {links.map((l) => (
                <path
                  key={l.id}
                  d={l.d}
                  fill="none"
                  strokeWidth={2}
                  strokeDasharray={l.open ? "6 6" : undefined}
                  className={l.open ? "stroke-ink-muted" : "stroke-ok/60"}
                  markerEnd="url(#dep-arrow)"
                />
              ))}
            </svg>
          )}

          {drag && (
            <div
              aria-hidden="true"
              className="absolute rounded-2xl border-2 border-dashed border-ink-muted/50"
              style={{ left: drag.ox, top: drag.oy, width: CARD_W, height: heights[drag.id] ?? 140 }}
            />
          )}

          {visible.map((p) => {
            const member = drag?.group?.find((m) => m.id === p.id);
            const shown =
              drag?.id === p.id ? { ...p, x: drag.x, y: drag.y }
              : member && drag ? { ...p, x: member.ox + drag.x - drag.ox, y: member.oy + drag.y - drag.oy }
              : p;
            return (
              <PlanCard
                key={p.id}
                plan={shown}
                tz={user.tz}
                lang={lang}
                selected={selected === p.id || multi.includes(p.id)}
                actions={selected === p.id && multi.length === 0}
                blocked={p.blocked_by.some((b) => openIds.has(b))}
                dragging={drag?.id === p.id || !!member}
                pulse={pulse === p.id}
                lowDetail={lowDetail}
                editing={editing === p.id}
                onPointerDown={onCardPointerDown}
                onKeyDown={onCardKey}
                onOpen={open}
                onQuickDone={quickDone}
                onDelete={remove}
                onRename={rename}
                measure={measure}
              />
            );
          })}
        </div>
      </div>

      {/* tools */}
      <div role="toolbar" aria-label={t("canvas.tools")} className="absolute left-3 top-3 flex flex-col gap-1 rounded-2xl border border-line bg-paper-2/95 p-1.5 shadow-card backdrop-blur">
        <button type="button" className="btn-icon bg-ink text-paper hover:bg-ink-2" aria-label={t("nav.newPlan")} title={t("nav.newPlan")} onClick={newCard}><Card /></button>
        <button type="button" className="btn-icon" aria-label={t("canvas.arrange")} title={t("canvas.arrange")} onClick={tidy} disabled={!plans.length}><Arrange /></button>
        <button type="button" className="btn-icon" aria-label={t("canvas.fit")} title={t("canvas.fit")} onClick={fit} disabled={!plans.length}><Fit /></button>
        <div className="mx-2 my-1 h-px bg-line" />
        <button type="button" className="btn-icon" aria-label={t("canvas.zoomIn")} onClick={() => zoomBy(1.25)}><Plus /></button>
        <span className="text-center font-mono text-[11px] text-ink-muted" aria-live="polite">{Math.round(view.zoom * 100)}%</span>
        <button type="button" className="btn-icon" aria-label={t("canvas.zoomOut")} onClick={() => zoomBy(0.8)}><Minus /></button>
      </div>

      {/* search */}
      <div className="absolute left-[76px] right-3 top-3 sm:right-auto sm:w-80">
        <label className="flex h-11 items-center gap-2 rounded-xl border border-line bg-surface px-3 shadow-card">
          <Search size={16} className="text-ink-muted" />
          <span className="sr-only">{t("canvas.search")}</span>
          <input
            type="search"
            role="combobox"
            aria-expanded={results.length > 0}
            aria-controls="search-results"
            aria-activedescendant={results[active] ? `sr-${results[active].id}` : undefined}
            value={query}
            placeholder={t("canvas.search")}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
              if (e.key === "Enter" && results[active]) { flyTo(results[active].id); setQuery(""); }
              if (e.key === "Escape") setQuery("");
            }}
            className="min-w-0 flex-1 bg-transparent text-[15px] outline-none"
          />
          {query && <button type="button" aria-label={t("common.close")} onClick={() => setQuery("")} className="text-ink-muted"><X size={16} /></button>}
        </label>
        {query && (
          <ul id="search-results" role="listbox" className="mt-1 overflow-hidden rounded-xl border border-line bg-surface shadow-lift">
            {results.length === 0 && <li className="px-3 py-2.5 text-sm text-ink-muted">{t("canvas.noResults")}</li>}
            {results.map((p, i) => (
              <li
                key={p.id}
                id={`sr-${p.id}`}
                role="option"
                aria-selected={i === active}
                onPointerDown={(e) => e.preventDefault()}
                onClick={() => { flyTo(p.id); setQuery(""); }}
                className={`cursor-pointer px-3 py-2.5 text-sm ${i === active ? "bg-accent-soft" : ""}`}
              >
                <div className="truncate font-bold">{p.title}</div>
                {p.tag && <div className="text-xs text-ink-muted">{p.tag}</div>}
              </li>
            ))}
          </ul>
        )}
      </div>

      {plans.length > 0 && (
        <Minimap plans={plans} heights={heights} view={view} size={size} onJump={(x, y) => animateTo(centerOn(x, y, size.w, size.h, viewRef.current.zoom))} />
      )}

      {!hintsHidden && plans.length > 0 && (
        <div className="absolute bottom-4 left-1/2 hidden -translate-x-1/2 items-center gap-3 whitespace-nowrap rounded-full bg-ink py-2 pl-4 pr-2 text-[13px] text-paper md:flex">
          <span><b>{t("canvas.hintDrag")}</b></span>
          <span className="opacity-40">|</span>
          <span>{t("canvas.hintOpen")}</span>
          <span className="opacity-40">|</span>
          <span>{t("canvas.hintDone")}</span>
          <span className="opacity-40">|</span>
          <span>{t("canvas.hintKeys")}</span>
          <span className="opacity-40">|</span>
          <span>{t("canvas.hintMulti")}</span>
          <button
            type="button"
            aria-label={t("canvas.hideHints")}
            className="flex h-8 w-8 items-center justify-center rounded-full hover:bg-surface/10"
            onClick={() => {
              setHintsHidden(true);
              try {
                localStorage.setItem(HINTS_KEY, "1");
              } catch {
                /* ignore */
              }
            }}
          >
            <X size={14} />
          </button>
        </div>
      )}
      {!hintsHidden && plans.length > 0 && (
        <div className="absolute bottom-4 left-3 rounded-full bg-ink px-3 py-1.5 text-xs text-paper md:hidden">{t("canvas.hintTouch")}</div>
      )}

      {multi.length > 0 && (
        <div role="toolbar" aria-label={t("canvas.bulk", { n: multi.length })} className="absolute bottom-4 left-1/2 z-20 flex max-w-[calc(100%-24px)] -translate-x-1/2 flex-wrap items-center gap-2 rounded-2xl border border-line bg-paper-2 p-2 shadow-lift">
          <span className="px-2 text-sm font-bold">{t("canvas.bulk", { n: multi.length })}</span>
          <span className="flex gap-1" role="group" aria-label={t("plan.color")}>
            {(["yellow", "mint", "lilac", "peach", "sky", "white"] as const).map((c) => (
              <button
                key={c}
                type="button"
                aria-label={`${t("plan.color")}: ${c}`}
                onClick={() => multi.forEach((id) => updatePlan(id, { color: c }))}
                className={`h-8 w-8 rounded-full ring-1 ring-black/10 ${CARD_BG[c]}`}
              />
            ))}
          </span>
          <label>
            <span className="sr-only">{t("plan.priority")}</span>
            <select
              className="field h-9 w-auto py-0 text-sm"
              defaultValue=""
              onChange={(e) => {
                const v = e.target.value as Plan["priority"];
                if (v) multi.forEach((id) => updatePlan(id, { priority: v }));
                e.target.value = "";
              }}
            >
              <option value="">{t("plan.priority")}…</option>
              {PRIORITIES.map((p) => <option key={p} value={p}>{t(`priority.${p}`)}</option>)}
            </select>
          </label>
          <button
            type="button"
            className="btn-danger h-9 px-3"
            onClick={() => {
              deletePlans(multi);
              setMulti([]);
            }}
          >
            {t("card.delete")}
          </button>
          <button type="button" className="btn-icon h-9 w-9" aria-label={t("common.close")} onClick={() => setMulti([])}><X size={16} /></button>
        </div>
      )}

      {loaded && plans.length === 0 && <EmptyState onBlank={newCard} />}
    </div>
  );
}
