"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { loadPlans, loadStats, signOut, useStore, useT } from "@/lib/store";
import { Bell, Grid, Inbox, ListIcon, Logo, Settings, Trash } from "@/components/Icons";
import { SyncBanner } from "@/components/SyncBanner";
import { ConflictDialog } from "@/components/ConflictDialog";
import { OverdueDialog } from "@/components/OverdueDialog";
import type { MessageKey } from "@/lib/i18n";

const NAV: { href: string; key: MessageKey; icon: typeof Grid }[] = [
  { href: "/canvas", key: "nav.canvas", icon: Grid },
  { href: "/list", key: "nav.list", icon: ListIcon },
  { href: "/inbox", key: "nav.inbox", icon: Inbox },
  { href: "/trash", key: "nav.trash", icon: Trash },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const t = useT();
  const router = useRouter();
  const path = usePathname();
  const ready = useStore((s) => s.ready);
  const user = useStore((s) => s.user);
  const stats = useStore((s) => s.stats);

  useEffect(() => {
    if (ready && !user) router.replace("/login");
  }, [ready, user, router]);

  useEffect(() => {
    if (!user) return;
    void loadPlans();
    void loadStats();
    const id = setInterval(() => void loadStats(), 60000);
    return () => clearInterval(id);
  }, [user]);

  if (!ready || !user) return null;
  const badge = (stats?.awaiting_my_approval ?? 0) + (stats?.unread_notifications ?? 0);

  return (
    <div className="flex min-h-dvh flex-col">
      <a href="#main" className="sr-only-focusable fixed left-2 top-2 z-50 rounded-lg bg-ink px-3 py-2 text-paper">Main</a>
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-paper-2 px-4 py-3 sm:px-6">
        <Link href="/canvas" className="flex items-center gap-2.5 rounded-lg">
          <span className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-ink text-paper"><Logo size={20} /></span>
          <span className="font-display text-[22px] font-extrabold tracking-tight">Reja<span className="text-accent">.</span></span>
        </Link>
        <nav aria-label={t("nav.main")} className="order-3 flex w-full gap-1 overflow-x-auto rounded-xl bg-paper-3 p-1 sm:order-none sm:w-auto">
          {NAV.map(({ href, key, icon: Icon }) => {
            const active = path.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`flex h-9 flex-1 items-center justify-center gap-2 whitespace-nowrap rounded-lg px-3 text-sm font-bold sm:flex-none ${active ? "bg-white text-ink shadow-sm" : "text-ink-3 hover:text-ink"}`}
              >
                <Icon size={16} />
                <span>{t(key)}</span>
                {href === "/inbox" && badge > 0 && (
                  <span className="min-w-5 rounded-full bg-warn px-1.5 text-center text-[11px] leading-5 text-white">{badge}</span>
                )}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <Link href="/inbox" aria-label={t("inbox.notifications")} className="btn-icon relative">
            <Bell />
            {(stats?.unread_notifications ?? 0) > 0 && <span className="absolute right-2.5 top-2.5 h-2.5 w-2.5 rounded-full bg-warn ring-2 ring-paper-2" />}
          </Link>
          <Link href="/settings" aria-label={t("nav.settings")} className="btn-icon"><Settings /></Link>
          <details className="relative">
            <summary
              aria-label={t("nav.profile")}
              className="flex h-11 w-11 cursor-pointer list-none items-center justify-center rounded-full border-2 border-white bg-[#FFB98A] text-[15px] font-extrabold text-[#5A2A0C] shadow-[0_0_0_1px_#E2DDD1] [&::-webkit-details-marker]:hidden"
            >
              {user.name.slice(0, 1).toUpperCase()}
            </summary>
            <div className="absolute right-0 z-30 mt-2 w-56 rounded-xl border border-line bg-white p-2 shadow-lift">
              <div className="px-3 py-2">
                <div className="truncate font-bold">{user.name}</div>
                <div className="truncate text-xs text-ink-muted">{user.email}</div>
              </div>
              <button
                type="button"
                onClick={() => { signOut(); router.replace("/login"); }}
                className="mt-1 h-10 w-full rounded-lg px-3 text-left text-sm font-bold hover:bg-paper-2"
              >
                {t("nav.logout")}
              </button>
            </div>
          </details>
        </div>
      </header>
      <SyncBanner />
      <div id="main" className="flex min-h-0 flex-1 flex-col">{children}</div>
      <ConflictDialog />
      <OverdueDialog />
    </div>
  );
}
