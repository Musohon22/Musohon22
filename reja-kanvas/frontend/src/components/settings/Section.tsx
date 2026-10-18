export function Section({ title, lead, children, danger = false }: { title: string; lead?: string; children: React.ReactNode; danger?: boolean }) {
  return (
    <section className={`flex flex-col gap-4 rounded-2xl border bg-surface p-6 ${danger ? "border-warn/40" : "border-line"}`}>
      <div>
        <h2 className={`font-display text-lg font-bold ${danger ? "text-warn-strong" : ""}`}>{title}</h2>
        {lead && <p className="mt-1 text-sm text-ink-3">{lead}</p>}
      </div>
      {children}
    </section>
  );
}
