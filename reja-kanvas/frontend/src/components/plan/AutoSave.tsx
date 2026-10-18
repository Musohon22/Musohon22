"use client";

import { useEffect, useRef, useState } from "react";

type Common = {
  value: string;
  onSave: (v: string) => void;
  disabled?: boolean;
  maxLength: number;
  className?: string;
  placeholder?: string;
  "aria-label"?: string;
  id?: string;
  required?: boolean;
  list?: string;
};

/** Text that saves itself shortly after typing stops and on blur; follows outside changes while not focused. */
function useAutoSave(value: string, onSave: (v: string) => void, required?: boolean) {
  const [draft, setDraft] = useState(value);
  const focused = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveRef = useRef(onSave);
  saveRef.current = onSave;

  useEffect(() => {
    if (!focused.current) setDraft(value);
  }, [value]);

  const commit = (v: string) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const trimmed = v.trim();
    if (required && !trimmed) return;
    if (trimmed !== value) saveRef.current(trimmed);
  };

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  return {
    value: draft,
    onFocus: () => (focused.current = true),
    onChange: (v: string) => {
      setDraft(v);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => commit(v), 700);
    },
    onBlur: () => {
      focused.current = false;
      commit(draft);
      if (required && !draft.trim()) setDraft(value);
    },
  };
}

export function AutoText({ value, onSave, required, ...rest }: Common) {
  const s = useAutoSave(value, onSave, required);
  return (
    <input
      {...rest}
      value={s.value}
      onFocus={s.onFocus}
      onBlur={s.onBlur}
      onChange={(e) => s.onChange(e.target.value)}
    />
  );
}

export function AutoArea({ value, onSave, required, rows = 2, singleLine = false, list: _list, ...rest }: Common & { rows?: number; singleLine?: boolean }) {
  const s = useAutoSave(value, onSave, required);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${el.scrollHeight}px`;
    }
  }, [s.value]);
  return (
    <textarea
      {...rest}
      ref={ref}
      rows={rows}
      value={s.value}
      onFocus={s.onFocus}
      onBlur={s.onBlur}
      onKeyDown={(e) => {
        if (singleLine && e.key === "Enter") {
          e.preventDefault();
          (e.target as HTMLTextAreaElement).blur();
        }
      }}
      onChange={(e) => s.onChange(singleLine ? e.target.value.replace(/\n/g, " ") : e.target.value)}
      style={{ resize: "none", overflow: "hidden" }}
    />
  );
}
