"use client";

import { useEffect, useRef, useState } from "react";
import type { Lang } from "./types";

const SPEECH_LANG: Record<Lang, string> = { uz: "uz-UZ", "uz-Cyrl": "uz-UZ", ru: "ru-RU", en: "en-US" };

interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start(): void;
  stop(): void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
}

/** Browser speech-to-text (Chrome, Edge, Safari). Text arrives through `onText`. */
export function useDictation(lang: Lang, onText: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const rec = useRef<Recognition | null>(null);
  const cb = useRef(onText);
  cb.current = onText;
  const Ctor =
    typeof window === "undefined"
      ? undefined
      : ((window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition }).SpeechRecognition ??
        (window as unknown as { webkitSpeechRecognition?: new () => Recognition }).webkitSpeechRecognition);

  useEffect(() => () => rec.current?.stop(), []);

  function start() {
    if (!Ctor || listening) return;
    const r = new Ctor();
    r.lang = SPEECH_LANG[lang];
    r.interimResults = true;
    r.continuous = false;
    r.onresult = (e) => {
      const text = Array.from(e.results).map((res) => res[0].transcript).join(" ");
      cb.current(text);
    };
    r.onend = () => setListening(false);
    r.onerror = () => setListening(false);
    rec.current = r;
    setListening(true);
    r.start();
  }

  function stop() {
    rec.current?.stop();
    setListening(false);
  }

  return { supported: !!Ctor, listening, start, stop };
}
