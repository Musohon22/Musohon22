"use client";

import { useEffect } from "react";
import { setUnauthorizedHandler } from "@/lib/api";
import { boot, signOut, toast, t, useStore } from "@/lib/store";
import { applyTheme, getTheme } from "@/lib/theme";
import { Toaster } from "./Toaster";

export function Providers({ children }: { children: React.ReactNode }) {
  const lang = useStore((s) => s.lang);

  useEffect(() => {
    boot();
    // follow the OS setting live while the theme is "system"
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => getTheme() === "system" && applyTheme("system");
    mq.addEventListener("change", onChange);
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
    setUnauthorizedHandler(() => {
      signOut();
      toast(t("err.invalid_token"), { tone: "error" });
      if (!location.pathname.startsWith("/login") && !location.pathname.startsWith("/s/")) location.assign("/login");
    });
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang === "uz-Cyrl" ? "uz-Cyrl" : lang;
  }, [lang]);

  return (
    <>
      {children}
      <Toaster />
    </>
  );
}
