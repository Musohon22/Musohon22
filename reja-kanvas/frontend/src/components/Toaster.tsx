"use client";

import { dismissToast, useStore, useT } from "@/lib/store";
import { Check, Alert, X } from "./Icons";

export function Toaster() {
  const toasts = useStore((s) => s.toasts);
  const t = useT();
  return (
    <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4">
      {toasts.map((item) => (
        <div
          key={item.id}
          role={item.tone === "error" ? "alert" : "status"}
          className="pointer-events-auto flex w-full max-w-md animate-rise items-center gap-3 overflow-hidden rounded-xl bg-ink px-4 py-3 text-sm text-paper shadow-lift"
        >
          <span className={item.tone === "error" ? "text-[#FF9B66]" : item.tone === "success" ? "text-[#7CE0A6]" : "text-paper/70"}>
            {item.tone === "error" ? <Alert /> : <Check />}
          </span>
          <span className="flex-1">{item.text}</span>
          {item.action && (
            <button
              type="button"
              className="relative h-9 overflow-hidden rounded-lg bg-paper px-3 font-bold text-ink"
              onClick={() => {
                item.action!.run();
                dismissToast(item.id);
              }}
            >
              {item.action.label}
              <span
                aria-hidden="true"
                className="absolute bottom-0 left-0 h-[3px] bg-accent"
                style={{ animation: `toastbar ${item.ms}ms linear forwards` }}
              />
            </button>
          )}
          <button type="button" aria-label={t("common.close")} onClick={() => dismissToast(item.id)} className="-mr-1 flex h-9 w-9 items-center justify-center rounded-lg text-paper/70 hover:text-paper">
            <X size={16} />
          </button>
        </div>
      ))}
    </div>
  );
}
