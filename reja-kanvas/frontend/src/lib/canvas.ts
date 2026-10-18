import { zoneOf, type Zone } from "./time";
import type { Plan } from "./types";

export const CARD_W = 300;
export const GRID = 20;
export const ZONE_W = 340;
export const ZONE_TOP = 40;
export const CARD_TOP = 90;
export const GAP = 20;

/** Column zones in world coordinates. Cards inside a column start at its x + 20. */
export const ZONES: { key: "today" | "tomorrow" | "week" | "later"; x: number }[] = [
  { key: "today", x: 20 },
  { key: "tomorrow", x: 380 },
  { key: "week", x: 740 },
  { key: "later", x: 1100 },
];

export const snap = (v: number) => Math.round(v / GRID) * GRID;

export interface View {
  x: number;
  y: number;
  zoom: number;
}

export const MIN_ZOOM = 0.25;
export const MAX_ZOOM = 2;
export const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function boundsOf(plans: Plan[], heights: Record<string, number>): Rect | null {
  if (!plans.length) return null;
  let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
  for (const p of plans) {
    x1 = Math.min(x1, p.x);
    y1 = Math.min(y1, p.y);
    x2 = Math.max(x2, p.x + CARD_W);
    y2 = Math.max(y2, p.y + (heights[p.id] ?? 160));
  }
  return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
}

/** A view that shows the whole rect inside a viewport of the given size. */
export function fitView(rect: Rect, vw: number, vh: number, pad = 60): View {
  const zoom = clampZoom(Math.min((vw - pad * 2) / rect.w, (vh - pad * 2) / rect.h, 1));
  return { zoom, x: (vw - rect.w * zoom) / 2 - rect.x * zoom, y: (vh - rect.h * zoom) / 2 - rect.y * zoom };
}

/** Centers the given world point in the viewport. */
export function centerOn(px: number, py: number, vw: number, vh: number, zoom: number): View {
  return { zoom, x: vw / 2 - px * zoom, y: vh / 2 - py * zoom };
}

const COLUMN: Record<Zone, number> = { overdue: 0, today: 0, tomorrow: 1, week: 2, later: 3, none: 3 };

/** "Tidy up": stacks every plan in its due-date column, ordered by due time, with no overlaps. */
export function arrange(plans: Plan[], tz: string, heights: Record<string, number>): { id: string; x: number; y: number }[] {
  const columns: Plan[][] = [[], [], [], []];
  for (const p of plans) columns[COLUMN[zoneOf(p, tz)]].push(p);
  const out: { id: string; x: number; y: number }[] = [];
  columns.forEach((col, i) => {
    col.sort((a, b) => (a.due_at ?? "9999").localeCompare(b.due_at ?? "9999") || a.created_at.localeCompare(b.created_at));
    let y = CARD_TOP;
    for (const p of col) {
      out.push({ id: p.id, x: ZONES[i].x + 20, y });
      y = snap(y + (heights[p.id] ?? 160) + GAP + GRID / 2);
    }
  });
  return out.filter((m) => {
    const p = plans.find((x) => x.id === m.id)!;
    return p.x !== m.x || p.y !== m.y;
  });
}

/** Where a new card goes: the first free slot in the "today" column, or the given point. */
export function freeSlot(plans: Plan[], heights: Record<string, number>, near?: { x: number; y: number }): { x: number; y: number } {
  const x = near ? snap(near.x) : ZONES[0].x + 20;
  let y = near ? snap(near.y) : CARD_TOP;
  const overlaps = (yy: number) =>
    plans.some((p) => Math.abs(p.x - x) < CARD_W && yy < p.y + (heights[p.id] ?? 160) + GAP && yy + 160 > p.y);
  let guard = 0;
  while (overlaps(y) && guard++ < 200) y += GRID * 2;
  return { x, y };
}
