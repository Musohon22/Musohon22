"use client";

import { useMemo } from "react";
import { Canvas } from "@/components/canvas/Canvas";
import { TodayPanel } from "@/components/TodayPanel";
import { BoardSwitcher } from "@/components/BoardSwitcher";
import { FilterBar } from "@/components/FilterBar";
import { filterCount, matches } from "@/lib/filter";
import { onBoard, useStore, useT } from "@/lib/store";

export default function CanvasPage() {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const planMap = useStore((s) => s.plans);
  const board = useStore((s) => s.board);
  const boards = useStore((s) => s.boards);
  const allItems = useStore((s) => s.items);
  const filter = useStore((s) => s.filter);

  const current = boards.find((b) => b.id === board);
  const readOnly = current?.role === "viewer";
  const plans = useMemo(() => Object.values(planMap).filter((p) => onBoard(p, board, user.id)), [planMap, board, user.id]);
  const items = useMemo(() => allItems.filter((i) => i.board_id === board), [allItems, board]);
  const dimmed = useMemo(() => {
    if (!filterCount(filter)) return undefined;
    return new Set(plans.filter((p) => !matches(p, filter, user.tz, user.id)).map((p) => p.id));
  }, [plans, filter, user.tz, user.id]);

  return (
    <div className="flex min-h-[calc(100dvh-140px)] flex-1 flex-col lg:min-h-0 lg:flex-row">
      <div className="flex h-[70dvh] min-w-0 flex-col lg:h-auto lg:flex-1">
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-paper-2 px-3 py-2">
          <BoardSwitcher />
          <FilterBar teamMode={!!current?.team_id} />
          {readOnly && <span className="text-sm font-semibold text-ink-muted">{t("board.viewOnly")}</span>}
        </div>
        <Canvas key={board ?? "personal"} plans={plans} items={items} board={board} readOnly={readOnly} dimmed={dimmed} />
      </div>
      <TodayPanel plans={plans} />
    </div>
  );
}
