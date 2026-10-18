"use client";

import { flush, useStore, useT } from "@/lib/store";
import { Wifi } from "./Icons";

/** Says plainly when we are offline or the server is unreachable, and how much is waiting. */
export function SyncBanner() {
  const t = useT();
  const online = useStore((s) => s.online);
  const serverDown = useStore((s) => s.serverDown);
  const queued = useStore((s) => s.outbox.length);
  if (online && !serverDown) return null;
  return (
    <div role="status" className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-warn/30 bg-warn-soft px-4 py-2 text-sm text-warn-ink sm:px-6">
      <span className="flex items-center gap-2 font-semibold">
        <Wifi size={16} />
        {online ? t("sync.serverDown") : t("sync.offline")}
      </span>
      {queued > 0 && <span>{t("sync.queued", { n: queued })}</span>}
      {online && (
        <button type="button" onClick={() => void flush()} className="ml-auto rounded-md px-2 py-1 font-bold underline underline-offset-2">
          {t("sync.retry")}
        </button>
      )}
    </div>
  );
}

/** Small "Saved / Saving… / Offline" label for one plan. */
export function SaveState({ planId }: { planId: string }) {
  const t = useT();
  const pending = useStore((s) => s.outbox.some((i) => i.planId === planId));
  const reachable = useStore((s) => s.online && !s.serverDown);
  const text = !pending ? t("sync.saved") : reachable ? t("sync.saving") : t("sync.offlineSaved");
  return (
    <span role="status" className={`text-sm font-semibold ${pending && !reachable ? "text-warn-ink" : pending ? "text-ink-muted" : "text-ok"}`}>
      {text}
    </span>
  );
}
