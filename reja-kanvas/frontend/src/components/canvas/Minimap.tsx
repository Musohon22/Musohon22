"use client";

import { boundsOf, CARD_W, type View } from "@/lib/canvas";
import { useT } from "@/lib/store";
import type { Plan } from "@/lib/types";

const W = 184;
const H = 120;
const FILL: Record<Plan["color"], string> = {
  yellow: "#F2C230", mint: "#3DB37A", lilac: "#7D6BE0", peach: "#FF9B66", sky: "#6B8CFF", white: "#A9A190",
};

/** Overview of the whole canvas; clicking jumps there, so no card is ever "lost". */
export function Minimap({
  plans, heights, view, size, onJump,
}: {
  plans: Plan[];
  heights: Record<string, number>;
  view: View;
  size: { w: number; h: number };
  onJump: (x: number, y: number) => void;
}) {
  const t = useT();
  const b = boundsOf(plans, heights)!;
  const vp = { x: -view.x / view.zoom, y: -view.y / view.zoom, w: size.w / view.zoom, h: size.h / view.zoom };
  const x1 = Math.min(b.x, vp.x) - 40;
  const y1 = Math.min(b.y, vp.y) - 40;
  const x2 = Math.max(b.x + b.w, vp.x + vp.w) + 40;
  const y2 = Math.max(b.y + b.h, vp.y + vp.h) + 40;
  const k = Math.min(W / (x2 - x1), H / (y2 - y1));

  return (
    <button
      type="button"
      aria-label={t("canvas.minimap")}
      title={t("canvas.minimap")}
      className="absolute bottom-3 right-3 hidden overflow-hidden rounded-xl border border-line bg-surface/95 p-0 shadow-card sm:block"
      style={{ width: W, height: H }}
      onClick={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        onJump(x1 + (e.clientX - r.left) / k, y1 + (e.clientY - r.top) / k);
      }}
    >
      <svg width={W} height={H} aria-hidden="true">
        {plans.map((p) => (
          <rect
            key={p.id}
            x={(p.x - x1) * k}
            y={(p.y - y1) * k}
            width={Math.max(3, CARD_W * k)}
            height={Math.max(2, (heights[p.id] ?? 160) * k)}
            rx={2}
            fill={FILL[p.color]}
            opacity={p.status === "done" || p.status === "cancelled" ? 0.4 : 0.9}
          />
        ))}
        <rect
          x={(vp.x - x1) * k}
          y={(vp.y - y1) * k}
          width={vp.w * k}
          height={vp.h * k}
          fill="rgba(43,89,255,.08)"
          stroke="#2B59FF"
          strokeWidth={1.5}
          rx={3}
        />
      </svg>
    </button>
  );
}
