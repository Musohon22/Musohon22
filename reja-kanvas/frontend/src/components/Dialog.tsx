"use client";

import { useEffect, useRef } from "react";
import { X } from "./Icons";
import { useT } from "@/lib/store";

/** Native <dialog>: focus trap, Esc to close and an inert background for free. */
export function Dialog({
  open,
  onClose,
  title,
  children,
  wide = false,
  dismissable = true,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  wide?: boolean;
  dismissable?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const t = useT();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        if (dismissable) onClose();
      }}
      onClick={(e) => {
        if (dismissable && e.target === ref.current) onClose();
      }}
      className={`m-auto w-[calc(100%-32px)] ${wide ? "max-w-2xl" : "max-w-md"} rounded-2xl border border-line bg-paper-2 p-0 text-ink shadow-paper backdrop:bg-ink/40`}
    >
      {open && (
        <div className="flex flex-col gap-4 p-6">
          <div className="flex items-start justify-between gap-4">
            <h2 className="font-display text-xl font-bold tracking-tight">{title}</h2>
            {dismissable && (
              <button type="button" onClick={onClose} aria-label={t("common.close")} className="btn-icon -m-2">
                <X />
              </button>
            )}
          </div>
          {children}
        </div>
      )}
    </dialog>
  );
}
