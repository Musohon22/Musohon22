"use client";

import { useEffect } from "react";
import { setUnauthorizedHandler } from "@/lib/api";
import { boot, signOut, toast, t, useStore } from "@/lib/store";
import { Toaster } from "./Toaster";

export function Providers({ children }: { children: React.ReactNode }) {
  const lang = useStore((s) => s.lang);

  useEffect(() => {
    boot();
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
