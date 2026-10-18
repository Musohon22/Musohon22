"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { INTL_LOCALE } from "@/lib/i18n";
import { useStore, useT } from "@/lib/store";
import { durationParts } from "@/lib/time";
import type { Analytics } from "@/lib/types";

const RANGES = [7, 30, 90];

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-2xl border border-line bg-surface p-4">
      <span className="text-xs font-semibold text-ink-muted">{label}</span>
      <span className="font-display text-3xl font-extrabold tracking-tight text-ink">{value}</span>
      {sub && <span className="text-xs text-ink-3">{sub}</span>}
    </div>
  );
}

/** Grouped vertical bars, one shared y-axis, hover tooltip per day. */
function DailyChart({ data, labelOf, tip }: { data: Analytics["series"]; labelOf: (d: string) => string; tip: (d: Analytics["series"][number]) => string }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 720;
  const H = 220;
  const pad = { l: 28, r: 8, t: 12, b: 26 };
  const max = Math.max(1, ...data.map((d) => Math.max(d.done, d.created)));
  const ticks = Array.from(new Set([0, Math.ceil(max / 2), max]));
  const slot = (W - pad.l - pad.r) / data.length;
  const bar = Math.max(2, Math.min(14, (slot - 6) / 2));
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - v / max);
  const every = Math.ceil(data.length / 8);
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-hidden="true">
        {ticks.map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} className="stroke-line-soft" strokeWidth={1} />
            <text x={pad.l - 6} y={y(v) + 4} textAnchor="end" className="fill-ink-muted" fontSize={11}>{v}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const cx = pad.l + slot * i + slot / 2;
          return (
            <g key={d.date} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={cx - slot / 2} y={pad.t} width={slot} height={H - pad.t - pad.b} fill="transparent" />
              {hover === i && <rect x={cx - slot / 2} y={pad.t} width={slot} height={H - pad.t - pad.b} className="fill-ink/5" />}
              {d.done > 0 && <path d={roundTop(cx - bar - 1, y(d.done), bar, y(0) - y(d.done))} className="fill-chart-1" />}
              {d.created > 0 && <path d={roundTop(cx + 1, y(d.created), bar, y(0) - y(d.created))} className="fill-chart-2" />}
              {i % every === 0 && (
                <text x={cx} y={H - 8} textAnchor="middle" className="fill-ink-muted" fontSize={11}>{labelOf(d.date)}</text>
              )}
            </g>
          );
        })}
        <line x1={pad.l} x2={W - pad.r} y1={y(0)} y2={y(0)} className="stroke-line-strong" strokeWidth={1} />
      </svg>
      {hover !== null && (
        <div
          role="status"
          className="pointer-events-none absolute top-0 -translate-x-1/2 rounded-lg bg-ink px-2.5 py-1.5 text-xs font-semibold text-paper shadow-lift"
          style={{ left: `${((pad.l + slot * hover + slot / 2) / W) * 100}%` }}
        >
          {tip(data[hover])}
        </div>
      )}
    </div>
  );
}

/** Bar with a 4px rounded data-end, anchored square to the baseline. */
function roundTop(x: number, y: number, w: number, h: number) {
  const r = Math.min(4, w / 2, h);
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
}

function HBars({ rows, format }: { rows: { label: string; value: number; secondary?: number }[]; format: (v: number) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.value + (r.secondary ?? 0)));
  return (
    <ul className="flex flex-col gap-2.5">
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[minmax(0,7rem)_1fr_auto] items-center gap-3 text-sm" title={`${r.label}: ${format(r.value)}${r.secondary !== undefined ? ` / ${r.secondary}` : ""}`}>
          <span className="truncate text-ink-2">{r.label}</span>
          <span className="flex h-3 gap-[2px]">
            <span className="h-3 rounded-r-[4px] bg-chart-1" style={{ width: `${(r.value / max) * 100}%` }} />
            {r.secondary !== undefined && r.secondary > 0 && <span className="h-3 rounded-r-[4px] bg-chart-2" style={{ width: `${(r.secondary / max) * 100}%` }} />}
          </span>
          <span className="font-mono text-xs text-ink-3">{format(r.value)}{r.secondary !== undefined ? ` · ${r.secondary}` : ""}</span>
        </li>
      ))}
    </ul>
  );
}

function Legend({ items }: { items: { label: string; className: string }[] }) {
  return (
    <div className="flex flex-wrap gap-4 text-xs text-ink-3">
      {items.map((i) => (
        <span key={i.label} className="flex items-center gap-1.5"><span className={`h-2.5 w-2.5 rounded-sm ${i.className}`} />{i.label}</span>
      ))}
    </div>
  );
}

export default function AnalyticsPage() {
  const t = useT();
  const lang = useStore((s) => s.lang);
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Analytics | null>(null);
  const [failed, setFailed] = useState(false);
  const [table, setTable] = useState(false);

  useEffect(() => {
    setFailed(false);
    api.get<Analytics>(`/api/analytics?days=${days}`).then(setData).catch(() => setFailed(true));
  }, [days]);

  const locale = INTL_LOCALE[lang];
  const short = (d: string) => new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(`${d}T00:00:00Z`));
  const dur = (minutes: number) => {
    const p = durationParts(minutes);
    return t(`common.${p.unit}`, { n: p.n });
  };
  const hours = (s: number) => (s >= 3600 ? `${(s / 3600).toFixed(1)} h` : `${Math.round(s / 60)} min`);

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="mr-auto font-display text-3xl font-extrabold tracking-tight">{t("an.title")}</h1>
        <div role="radiogroup" aria-label={t("an.range")} className="flex rounded-xl bg-paper-3 p-1">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              role="radio"
              aria-checked={days === r}
              onClick={() => setDays(r)}
              className={`h-9 rounded-lg px-3 text-sm font-bold ${days === r ? "bg-surface shadow-sm" : "text-ink-3"}`}
            >
              {t("an.days", { n: r })}
            </button>
          ))}
        </div>
      </div>

      {failed && <p className="rounded-xl bg-warn-soft p-4 text-warn-ink">{t("err.network")}</p>}
      {!data && !failed && <p className="text-ink-muted">{t("common.loading")}</p>}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Tile label={t("an.done")} value={String(data.total_done)} sub={`${t("an.created")}: ${data.total_created}`} />
            <Tile
              label={t("an.onTimeRate")}
              value={data.on_time_rate === null ? "—" : `${Math.round(data.on_time_rate * 100)}%`}
              sub={data.avg_late_minutes ? `${t("an.avgLate")}: ${dur(data.avg_late_minutes)}` : undefined}
            />
            <Tile label={t("an.streak")} value={t("an.daysUnit", { n: data.streak })} sub={`${t("an.best")}: ${data.best_streak}`} />
            <Tile label={t("an.open")} value={String(data.open_now)} sub={data.overdue_now ? `${t("an.overdue")}: ${data.overdue_now}` : undefined} />
          </div>

          <section className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-5">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="mr-auto font-display text-lg font-bold">{t("an.daily")}</h2>
              <Legend items={[{ label: t("an.done"), className: "bg-chart-1" }, { label: t("an.created"), className: "bg-chart-2" }]} />
              <button type="button" className="text-sm font-semibold text-accent-ink underline underline-offset-2" aria-pressed={table} onClick={() => setTable((v) => !v)}>
                {t("an.table")}
              </button>
            </div>
            {data.total_done + data.total_created === 0 ? (
              <p className="text-sm text-ink-muted">{t("an.noData")}</p>
            ) : table ? (
              <div className="max-h-72 overflow-auto">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-ink-muted"><th className="py-1 font-semibold">{t("an.date")}</th><th className="font-semibold">{t("an.done")}</th><th className="font-semibold">{t("an.created")}</th></tr></thead>
                  <tbody>
                    {data.series.map((d) => (
                      <tr key={d.date} className="border-t border-line-soft"><td className="py-1">{short(d.date)}</td><td>{d.done}</td><td>{d.created}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <DailyChart data={data.series} labelOf={short} tip={(d) => t("an.tip", { date: short(d.date), done: d.done, created: d.created })} />
            )}
          </section>

          <div className="grid gap-4 md:grid-cols-2">
            <section className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-5">
              <h2 className="font-display text-lg font-bold">{t("an.weekday")}</h2>
              <HBars rows={data.weekday_done.map((v, i) => ({ label: t(`wd.${i}` as "wd.0"), value: v }))} format={String} />
            </section>
            <section className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-5">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="mr-auto font-display text-lg font-bold">{t("an.byTag")}</h2>
                <Legend items={[{ label: t("an.done"), className: "bg-chart-1" }, { label: t("an.open"), className: "bg-chart-2" }]} />
              </div>
              {data.by_tag.length === 0 ? (
                <p className="text-sm text-ink-muted">{t("an.noData")}</p>
              ) : (
                <HBars rows={data.by_tag.map((r) => ({ label: r.tag || t("an.untagged"), value: r.done, secondary: r.open }))} format={String} />
              )}
            </section>
          </div>

          <section className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-5">
            <h2 className="font-display text-lg font-bold">{t("an.time")}</h2>
            {data.tracked_total === 0 ? (
              <p className="text-sm text-ink-muted">{t("timer.pomodoro")}</p>
            ) : (
              <HBars rows={data.tracked_by_tag.map((r) => ({ label: r.tag || t("an.untagged"), value: r.seconds }))} format={hours} />
            )}
          </section>
        </>
      )}
    </main>
  );
}
