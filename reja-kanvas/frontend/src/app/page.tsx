"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useStore } from "@/lib/store";

export default function Home() {
  const router = useRouter();
  const ready = useStore((s) => s.ready);
  const user = useStore((s) => s.user);

  useEffect(() => {
    if (ready) router.replace(user ? "/canvas" : "/login");
  }, [ready, user, router]);

  return null;
}
