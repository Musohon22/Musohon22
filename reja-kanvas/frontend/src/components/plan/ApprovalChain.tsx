"use client";

import { patchDetail, updatePlan, useT } from "@/lib/store";
import type { Person, PlanDetail } from "@/lib/types";
import { PeoplePicker } from "./PeoplePicker";

/** Approvers after the main one, each a stage in order (up to 4 more). */
export function ApprovalChain({ plan, disabled }: { plan: PlanDetail; disabled: boolean }) {
  const t = useT();
  if (!plan.approver) return null;
  const extra = (plan.chain ?? []).slice(1).filter(Boolean) as Person[];

  const save = (people: Person[]) => {
    updatePlan(plan.id, { approval_chain: people.map((p) => p.id) });
    patchDetail(plan.id, { chain: [plan.approver, ...people], approval_chain: people.map((p) => p.id) });
  };

  return (
    <div className="flex flex-col gap-2 sm:col-span-2">
      <span className="label">{t("plan.chain")}</span>
      <span className="text-xs text-ink-muted">{t("plan.chainHint")}</span>
      {extra.map((p, i) => (
        <PeoplePicker
          key={p.id}
          label={t("plan.stageN", { n: i + 2 })}
          person={p}
          disabled={disabled}
          onChange={(np) => save(np ? extra.map((x, j) => (j === i ? np : x)) : extra.filter((_, j) => j !== i))}
        />
      ))}
      {!disabled && extra.length < 4 && (
        <PeoplePicker label={t("plan.stageN", { n: extra.length + 2 })} person={null} disabled={disabled} onChange={(np) => np && save([...extra, np])} />
      )}
    </div>
  );
}
