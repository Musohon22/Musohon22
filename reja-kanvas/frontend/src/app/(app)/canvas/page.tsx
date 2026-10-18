"use client";

import { useMemo } from "react";
import { Canvas } from "@/components/canvas/Canvas";
import { TodayPanel } from "@/components/TodayPanel";
import { useStore } from "@/lib/store";

export default function CanvasPage() {
  const planMap = useStore((s) => s.plans);
  const plans = useMemo(() => Object.values(planMap), [planMap]);
  return (
    <div className="flex min-h-[calc(100dvh-140px)] flex-1 flex-col lg:min-h-0 lg:flex-row">
      <div className="flex h-[70dvh] min-w-0 flex-col lg:h-auto lg:flex-1">
        <Canvas plans={plans} />
      </div>
      <TodayPanel plans={plans} />
    </div>
  );
}
