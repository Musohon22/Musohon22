"use client";

import { useEffect, useRef, useState } from "react";
import { useT } from "@/lib/store";

/** Draw a signature with finger, pen or mouse. Emits a PNG data URL, or null when cleared. */
export function SignaturePad({ onChange, label }: { onChange: (png: string | null) => void; label: string }) {
  const t = useT();
  const canvas = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const [empty, setEmpty] = useState(true);

  useEffect(() => {
    const c = canvas.current!;
    const ratio = window.devicePixelRatio || 1;
    c.width = c.offsetWidth * ratio;
    c.height = c.offsetHeight * ratio;
    const ctx = c.getContext("2d")!;
    ctx.scale(ratio, ratio);
    ctx.lineWidth = 2.4;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#1B1D22";
  }, []);

  const point = (e: React.PointerEvent) => {
    const r = canvas.current!.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top] as const;
  };

  return (
    <div className="flex flex-col gap-1.5">
      <span className="label">{label}</span>
      <canvas
        ref={canvas}
        role="img"
        aria-label={t("sig.hint")}
        className="h-28 w-full touch-none rounded-xl border border-dashed border-line-strong bg-white"
        onPointerDown={(e) => {
          drawing.current = true;
          canvas.current!.setPointerCapture(e.pointerId);
          const ctx = canvas.current!.getContext("2d")!;
          const [x, y] = point(e);
          ctx.beginPath();
          ctx.moveTo(x, y);
        }}
        onPointerMove={(e) => {
          if (!drawing.current) return;
          const ctx = canvas.current!.getContext("2d")!;
          const [x, y] = point(e);
          ctx.lineTo(x, y);
          ctx.stroke();
        }}
        onPointerUp={() => {
          if (!drawing.current) return;
          drawing.current = false;
          setEmpty(false);
          onChange(canvas.current!.toDataURL("image/png"));
        }}
      />
      <div className="flex items-center justify-between text-xs text-ink-muted">
        <span>{t("sig.hint")}</span>
        {!empty && (
          <button
            type="button"
            className="font-semibold underline"
            onClick={() => {
              const c = canvas.current!;
              c.getContext("2d")!.clearRect(0, 0, c.width, c.height);
              setEmpty(true);
              onChange(null);
            }}
          >
            {t("sig.clear")}
          </button>
        )}
      </div>
    </div>
  );
}
