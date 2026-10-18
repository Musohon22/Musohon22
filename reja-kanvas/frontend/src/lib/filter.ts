import { normalize } from "./search";
import { zoneOf } from "./time";
import type { FilterQuery, Plan } from "./types";

export function filterCount(f: FilterQuery): number {
  return (f.text ? 1 : 0) + f.tags.length + f.priorities.length + f.statuses.length + (f.due ? 1 : 0) + (f.mine_only ? 1 : 0);
}

export function matches(plan: Plan, f: FilterQuery, tz: string, userId: string): boolean {
  if (f.text && !normalize(`${plan.title} ${plan.tag ?? ""}`).includes(normalize(f.text))) return false;
  if (f.tags.length && !f.tags.includes(plan.tag ?? "")) return false;
  if (f.priorities.length && !f.priorities.includes(plan.priority)) return false;
  if (f.statuses.length && !f.statuses.includes(plan.status)) return false;
  if (f.mine_only && plan.owner_id !== userId) return false;
  if (f.due) {
    const z = zoneOf(plan, tz);
    if (f.due === "overdue" && z !== "overdue") return false;
    if (f.due === "today" && z !== "today") return false;
    if (f.due === "week" && !["today", "tomorrow", "week"].includes(z)) return false;
    if (f.due === "none" && plan.due_at) return false;
  }
  return true;
}
