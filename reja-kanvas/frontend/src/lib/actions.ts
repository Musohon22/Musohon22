"use client";

import { planAction, t, toast } from "./store";
import type { Plan, Rating } from "./types";

/** Can this plan be finished with one tap, or does it need the confirmation panel? */
export function needsConfirmPanel(plan: Plan): boolean {
  return !!plan.approver_id || plan.require_proof || plan.progress.done < plan.progress.total;
}

/** Submits a plan. When it completes at once, offers a 10-second undo. */
export async function submitWithUndo(planId: string, body: { final_note?: string; rating?: Rating | null; signature?: string } = {}) {
  const detail = await planAction(planId, "submit", body);
  if (!detail) return undefined;
  if (detail.status === "done") {
    toast(t("confirm.doneToast"), {
      tone: "success",
      action: {
        label: t("confirm.undo"),
        run: () => {
          void planAction(planId, "reopen", { reason: "undo" }).then((d) => d && toast(t("confirm.undone")));
        },
      },
    });
  } else {
    toast(t("confirm.sentToast"), { tone: "success" });
  }
  return detail;
}
