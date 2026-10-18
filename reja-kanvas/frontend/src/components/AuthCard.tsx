import { Logo } from "./Icons";

export function AuthCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main className="canvas-dots flex min-h-dvh items-center justify-center bg-[length:22px_22px] p-4">
      <section className="flex w-full max-w-md flex-col gap-5 rounded-3xl border border-line bg-paper-2 p-8 shadow-lift">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-ink text-paper"><Logo size={20} /></span>
          <span className="font-display text-[22px] font-extrabold">Reja<span className="text-accent">.</span></span>
        </div>
        <h1 className="font-display text-3xl font-extrabold tracking-tight">{title}</h1>
        {children}
      </section>
    </main>
  );
}
