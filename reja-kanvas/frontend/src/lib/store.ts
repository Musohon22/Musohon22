"use client";

/**
 * Client state with an offline-first outbox.
 *
 * Every edit is applied to local state at once and queued. The queue is flushed in order
 * whenever the server is reachable; it survives reloads (localStorage). Creates carry
 * client-generated ids so the server can de-duplicate retries. Patches carry the version
 * the edit started from; a 409 "conflict" becomes a Conflict the user resolves field by field.
 */

import { useSyncExternalStore } from "react";
import { api, ApiError, NetworkError, setToken, uuid } from "./api";
import { translate, errorKey, type MessageKey, type Vars } from "./i18n";
import type {
  Conflict, Lang, Plan, PlanChanges, PlanDetail, Stats, Step, StepStatus, User,
} from "./types";

type OutboxItem =
  | { id: string; kind: "create"; planId: string; body: Record<string, unknown> }
  | { id: string; kind: "patch"; planId: string; base: number; changes: PlanChanges }
  | { id: string; kind: "move"; planId: string; x: number; y: number }
  | { id: string; kind: "delete"; planId: string }
  | { id: string; kind: "restore"; planId: string }
  | { id: string; kind: "step_add"; planId: string; stepId: string; text: string; position: number }
  | { id: string; kind: "step_patch"; planId: string; stepId: string; changes: Partial<Pick<Step, "text" | "status" | "position">> }
  | { id: string; kind: "step_delete"; planId: string; stepId: string };

export interface Toast {
  id: string;
  text: string;
  tone: "info" | "success" | "error";
  action?: { label: string; run: () => void };
  ms: number;
}

export interface State {
  ready: boolean;
  user: User | null;
  lang: Lang;
  plans: Record<string, Plan>;
  details: Record<string, PlanDetail>;
  loaded: boolean;
  online: boolean;
  serverDown: boolean;
  flushing: boolean;
  outbox: OutboxItem[];
  conflicts: Conflict[];
  stats: Stats | null;
  toasts: Toast[];
}

const LS = { user: "reja.user", lang: "reja.lang", plans: "reja.plans", details: "reja.details", outbox: "reja.outbox" };

let state: State = {
  ready: false,
  user: null,
  lang: "uz",
  plans: {},
  details: {},
  loaded: false,
  online: true,
  serverDown: false,
  flushing: false,
  outbox: [],
  conflicts: [],
  stats: null,
  toasts: [],
};
const listeners = new Set<() => void>();

function set(patch: Partial<State>) {
  state = { ...state, ...patch };
  persist(patch);
  listeners.forEach((l) => l());
}

export function getState() {
  return state;
}

export function useStore<T>(selector: (s: State) => T): T {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => selector(state),
    () => selector(state),
  );
}

// ---- persistence ----------------------------------------------------------------------

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  try {
    if (value === null || value === undefined) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* quota or private mode: state stays in memory */
  }
}

let persistTimer: ReturnType<typeof setTimeout> | null = null;
function persist(patch: Partial<State>) {
  if (typeof window === "undefined" || !state.ready) return;
  if ("user" in patch) write(LS.user, state.user);
  if ("lang" in patch) write(LS.lang, state.lang);
  if ("outbox" in patch) write(LS.outbox, state.outbox); // the queue is written at once: it must survive a crash
  if ("plans" in patch || "details" in patch) {
    if (persistTimer) clearTimeout(persistTimer);
    persistTimer = setTimeout(() => {
      write(LS.plans, state.plans);
      // keep the 30 most recently updated documents for offline reading
      const recent = Object.values(state.details)
        .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
        .slice(0, 30);
      write(LS.details, Object.fromEntries(recent.map((d) => [d.id, d])));
    }, 300);
  }
}

// ---- i18n & toasts --------------------------------------------------------------------

export function t(key: MessageKey, vars?: Vars) {
  return translate(state.lang, key, vars);
}

export function useT() {
  const lang = useStore((s) => s.lang);
  return (key: MessageKey, vars?: Vars) => translate(lang, key, vars);
}

export function toast(text: string, opts: Partial<Omit<Toast, "id" | "text">> = {}) {
  const item: Toast = { id: uuid(), text, tone: opts.tone ?? "info", action: opts.action, ms: opts.ms ?? (opts.action ? 10000 : 4000) };
  set({ toasts: [...state.toasts.slice(-3), item] });
  setTimeout(() => dismissToast(item.id), item.ms);
  return item.id;
}

export function dismissToast(id: string) {
  if (state.toasts.some((x) => x.id === id)) set({ toasts: state.toasts.filter((x) => x.id !== id) });
}

/** User-facing message for any thrown error. */
export function errorText(e: unknown): string {
  if (e instanceof NetworkError) return t("err.network");
  if (e instanceof ApiError) return t(errorKey(e.code));
  return t("err.unknown");
}

export function toastError(e: unknown) {
  toast(errorText(e), { tone: "error" });
}

// ---- session --------------------------------------------------------------------------

export function boot() {
  if (state.ready) return;
  const user = read<User | null>(LS.user, null);
  const lang = read<Lang>(LS.lang, user?.lang ?? "uz");
  state = {
    ...state,
    ready: true,
    user,
    lang,
    plans: read(LS.plans, {}),
    details: read(LS.details, {}),
    outbox: read(LS.outbox, []),
    online: typeof navigator === "undefined" ? true : navigator.onLine,
  };
  listeners.forEach((l) => l());
  window.addEventListener("online", () => {
    set({ online: true });
    void flush();
  });
  window.addEventListener("offline", () => set({ online: false }));
  // Heartbeat: retries the queue and notices when a down server comes back.
  setInterval(() => {
    if (state.user && (state.outbox.length || state.serverDown)) void flush();
  }, 15000);
  if (user) void flush();
}

export function signedIn(token: string, user: User) {
  setToken(token);
  set({ user, lang: user.lang, plans: {}, details: {}, outbox: [], conflicts: [], loaded: false, stats: null });
}

export function signOut() {
  setToken(null);
  set({ user: null, plans: {}, details: {}, outbox: [], conflicts: [], loaded: false, stats: null });
}

export function setLang(lang: Lang) {
  set({ lang });
}

export function setUser(user: User) {
  set({ user, lang: user.lang });
}

// ---- reachability ---------------------------------------------------------------------

function markReachable() {
  if (state.serverDown || !state.online) set({ serverDown: false, online: true });
}

function markUnreachable() {
  if (!state.serverDown) set({ serverDown: true });
}

/** Run an online-only action (submit, approve, upload…), translating failures to toasts. */
export async function online<T>(fn: () => Promise<T>): Promise<T | undefined> {
  if (!state.online) {
    toast(t("err.offline_action"), { tone: "error" });
    return undefined;
  }
  try {
    const out = await fn();
    markReachable();
    return out;
  } catch (e) {
    if (e instanceof NetworkError) markUnreachable();
    toastError(e);
    return undefined;
  }
}

// ---- loading --------------------------------------------------------------------------

/** Re-applies queued (unsent) edits over fresh server data so a reload never "loses" them. */
function overlay(plans: Record<string, Plan>): Record<string, Plan> {
  const out = { ...plans };
  for (const item of state.outbox) {
    const p = out[item.planId];
    switch (item.kind) {
      case "create":
        if (!p && state.plans[item.planId]) out[item.planId] = state.plans[item.planId];
        break;
      case "patch":
        if (p) out[item.planId] = { ...p, ...item.changes } as Plan;
        break;
      case "move":
        if (p) out[item.planId] = { ...p, x: item.x, y: item.y };
        break;
      case "delete":
        delete out[item.planId];
        break;
      case "restore":
        break;
    }
  }
  return out;
}

export async function loadPlans() {
  try {
    const { plans } = await api.get<{ plans: Plan[] }>("/api/plans");
    markReachable();
    set({ plans: overlay(Object.fromEntries(plans.map((p) => [p.id, p]))), loaded: true });
  } catch (e) {
    if (e instanceof NetworkError) markUnreachable();
    set({ loaded: true }); // cached plans stay on screen
  }
}

export async function loadStats() {
  try {
    set({ stats: await api.get<Stats>("/api/stats") });
  } catch {
    /* the panel keeps the last known numbers */
  }
}

function draftDetail(plan: Plan): PlanDetail {
  return { ...plan, body_html: "", steps: [], attachments: [], owner: null, approver: null, backup_approver: null, approved_by: null, blockers: [] };
}

export async function loadDetail(id: string): Promise<PlanDetail | null> {
  // A plan created offline exists only locally until its create request goes through.
  if (state.outbox.some((i) => i.kind === "create" && i.planId === id)) {
    await flush();
    if (state.outbox.some((i) => i.kind === "create" && i.planId === id)) {
      const local = state.details[id] ?? (state.plans[id] ? draftDetail(state.plans[id]) : null);
      if (local && !state.details[id]) storeDetail(local);
      return local;
    }
  }
  try {
    let detail = await api.get<PlanDetail>(`/api/plans/${id}`);
    markReachable();
    for (const item of state.outbox) {
      if (item.planId !== id) continue;
      if (item.kind === "patch") detail = { ...detail, ...item.changes } as PlanDetail;
      if (item.kind === "step_add" && !detail.steps.some((s) => s.id === item.stepId))
        detail = { ...detail, steps: [...detail.steps, { id: item.stepId, text: item.text, status: "todo", position: item.position, done_at: null }] };
      if (item.kind === "step_patch") detail = { ...detail, steps: detail.steps.map((s) => (s.id === item.stepId ? { ...s, ...item.changes } : s)) };
      if (item.kind === "step_delete") detail = { ...detail, steps: detail.steps.filter((s) => s.id !== item.stepId) };
    }
    storeDetail(detail);
    return detail;
  } catch (e) {
    if (e instanceof NetworkError) markUnreachable();
    else if (e instanceof ApiError && e.status === 404) {
      const { [id]: _gone, ...rest } = state.details;
      set({ details: rest });
      throw e;
    }
    return state.details[id] ?? null;
  }
}

/** Puts a server copy of a plan into both the list and the detail cache. */
export function storeDetail(detail: PlanDetail) {
  const { body_html: _b, steps: _s, attachments: _a, approver: _ap, backup_approver: _bp, approved_by: _ab, blockers: _bl, ...listPart } = detail;
  const plans = { ...state.plans };
  if (!detail.deleted_at && detail.my_role === "owner") plans[detail.id] = { ...(plans[detail.id] ?? {}), ...listPart } as Plan;
  set({ details: { ...state.details, [detail.id]: detail }, plans });
}

// ---- local mutations ------------------------------------------------------------------

function enqueue(item: OutboxItem) {
  const last = state.outbox[state.outbox.length - 1];
  // Coalesce bursts (typing, dragging) into one request.
  if (last && last.planId === item.planId && !state.flushing) {
    if (item.kind === "patch" && last.kind === "patch") {
      set({ outbox: [...state.outbox.slice(0, -1), { ...last, changes: { ...last.changes, ...item.changes } }] });
      scheduleFlush();
      return;
    }
    if (item.kind === "move" && last.kind === "move") {
      set({ outbox: [...state.outbox.slice(0, -1), { ...last, x: item.x, y: item.y }] });
      scheduleFlush();
      return;
    }
  }
  set({ outbox: [...state.outbox, item] });
  scheduleFlush();
}

let flushTimer: ReturnType<typeof setTimeout> | null = null;
function scheduleFlush(ms = 600) {
  if (flushTimer) clearTimeout(flushTimer);
  flushTimer = setTimeout(() => void flush(), ms);
}

function patchLocal(id: string, changes: Partial<PlanDetail>) {
  const plans = state.plans[id] ? { ...state.plans, [id]: { ...state.plans[id], ...changes } as Plan } : state.plans;
  const details = state.details[id] ? { ...state.details, [id]: { ...state.details[id], ...changes } } : state.details;
  set({ plans, details });
}

function knownVersion(id: string) {
  return state.details[id]?.version ?? state.plans[id]?.version ?? 1;
}

export function createPlan(fields: Partial<Plan> & { title: string; x: number; y: number; steps?: string[] }): string {
  const id = uuid();
  const now = new Date().toISOString();
  const { steps, ...rest } = fields;
  const plan: Plan = {
    id, tag: null, color: "yellow", due_at: null, remind_minutes: null, goal: "", done_criteria: "",
    require_proof: false, status: "active", submitted_at: null, completed_at: null, approved_at: null,
    late_minutes: null, rating: null, final_note: null, return_reason: null, escalated_at: null,
    version: 1, deleted_at: null, created_at: now, updated_at: now, owner_id: state.user?.id ?? "",
    approver_id: null, backup_approver_id: null, my_role: "owner", can_decide: false,
    priority: "normal", recurrence: null, series_id: null, next_occurrence_id: null, archived_at: null,
    tracked_seconds: 0, timer_started_at: null, blocked_by: [],
    progress: { done: 0, total: steps?.length ?? 0, cancelled: 0 },
    ...rest,
  };
  set({ plans: { ...state.plans, [id]: plan } });
  const body: Record<string, unknown> = {
    id, title: plan.title, x: plan.x, y: plan.y, color: plan.color, tag: plan.tag, due_at: plan.due_at,
    priority: plan.priority, recurrence: plan.recurrence,
  };
  if (steps?.length) body.steps = steps;
  enqueue({ id: uuid(), kind: "create", planId: id, body });
  return id;
}

export function updatePlan(id: string, changes: PlanChanges) {
  patchLocal(id, changes);
  enqueue({ id: uuid(), kind: "patch", planId: id, base: knownVersion(id), changes });
}

export function movePlan(id: string, x: number, y: number) {
  patchLocal(id, { x, y });
  enqueue({ id: uuid(), kind: "move", planId: id, x, y });
}

export function movePlans(items: { id: string; x: number; y: number }[]) {
  for (const it of items) movePlan(it.id, it.x, it.y);
}

/** Moves plans to the trash with one 10-second "Undo" toast. */
export function deletePlans(ids: string[]) {
  const removed = ids.map((id) => state.plans[id]).filter(Boolean);
  const plans = { ...state.plans };
  for (const id of ids) delete plans[id];
  set({ plans });
  const itemIds = ids.map((planId) => {
    const itemId = uuid();
    enqueue({ id: itemId, kind: "delete", planId });
    return itemId;
  });
  toast(t("trash.deleted"), {
    action: {
      label: t("confirm.undo"),
      run: () => {
        ids.forEach((id, i) => {
          const stillQueued = state.outbox.some((x) => x.id === itemIds[i]);
          if (stillQueued) set({ outbox: state.outbox.filter((x) => x.id !== itemIds[i]) });
          else enqueue({ id: uuid(), kind: "restore", planId: id });
        });
        set({ plans: { ...state.plans, ...Object.fromEntries(removed.map((p) => [p.id, p])) } });
      },
    },
  });
}

export function deletePlan(id: string) {
  deletePlans([id]);
}

export function restorePlan(id: string) {
  enqueue({ id: uuid(), kind: "restore", planId: id });
}

export function addStep(planId: string, text: string) {
  const d = state.details[planId];
  if (!d) return;
  const step: Step = { id: uuid(), text, status: "todo", position: d.steps.length, done_at: null };
  const steps = [...d.steps, step];
  setSteps(planId, steps);
  enqueue({ id: uuid(), kind: "step_add", planId, stepId: step.id, text, position: step.position });
}

export function updateStep(planId: string, stepId: string, changes: { text?: string; status?: StepStatus }) {
  const d = state.details[planId];
  if (!d) return;
  setSteps(planId, d.steps.map((s) => (s.id === stepId ? { ...s, ...changes } : s)));
  enqueue({ id: uuid(), kind: "step_patch", planId, stepId, changes });
}

export function deleteStep(planId: string, stepId: string) {
  const d = state.details[planId];
  if (!d) return;
  setSteps(planId, d.steps.filter((s) => s.id !== stepId));
  enqueue({ id: uuid(), kind: "step_delete", planId, stepId });
}

function setSteps(planId: string, steps: Step[]) {
  const live = steps.filter((s) => s.status !== "cancelled");
  const progress = { done: live.filter((s) => s.status === "done").length, total: live.length, cancelled: steps.length - live.length };
  patchLocal(planId, { steps, progress } as Partial<PlanDetail>);
}

export function pendingFor(planId: string) {
  return state.outbox.some((i) => i.planId === planId);
}

// ---- flushing -------------------------------------------------------------------------

let flushPromise: Promise<void> | null = null;

/** Sends queued edits in order. Resolves when the queue is empty or the server is unreachable. */
export function flush(): Promise<void> {
  if (!flushPromise) {
    flushPromise = doFlush().finally(() => {
      flushPromise = null;
    });
  }
  return flushPromise;
}

async function doFlush() {
  if (!state.user || !state.outbox.length) return;
  set({ flushing: true });
  try {
    while (state.outbox.length) {
      const item = state.outbox[0];
      try {
        await send(item);
        markReachable();
        set({ outbox: state.outbox.filter((i) => i.id !== item.id) });
      } catch (e) {
        if (e instanceof NetworkError || (e instanceof ApiError && e.status >= 500)) {
          markUnreachable();
          return; // keep the item; the heartbeat retries
        }
        if (e instanceof ApiError && e.status === 401) return;
        set({ outbox: state.outbox.filter((i) => i.id !== item.id) });
        handleRejected(item, e);
      }
    }
  } finally {
    set({ flushing: false });
  }
}

async function send(item: OutboxItem) {
  switch (item.kind) {
    case "create": {
      const detail = await api.post<PlanDetail>("/api/plans", item.body);
      storeDetailKeepingLocal(detail, item.id);
      return;
    }
    case "patch": {
      const detail = await api.patch<PlanDetail>(`/api/plans/${item.planId}`, { base_version: item.base, ...item.changes });
      // Later queued patches were made on top of this one: they start from the new version.
      set({
        outbox: state.outbox.map((i) => (i.kind === "patch" && i.planId === item.planId && i.id !== item.id ? { ...i, base: detail.version } : i)),
      });
      storeDetailKeepingLocal(detail, item.id);
      return;
    }
    case "move":
      await api.post("/api/plans/batch-move", { items: [{ id: item.planId, x: item.x, y: item.y }] });
      return;
    case "delete":
      await api.del(`/api/plans/${item.planId}`);
      return;
    case "restore": {
      const detail = await api.post<PlanDetail>(`/api/plans/${item.planId}/restore`);
      storeDetail(detail);
      return;
    }
    case "step_add":
      await api.post(`/api/plans/${item.planId}/steps`, { id: item.stepId, text: item.text, position: item.position });
      return;
    case "step_patch":
      await api.patch(`/api/steps/${item.stepId}`, item.changes);
      return;
    case "step_delete":
      try {
        await api.del(`/api/steps/${item.stepId}`);
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 404)) throw e; // already gone is fine
      }
      return;
  }
}

/** Takes the server's version number and status but keeps fields the user is still editing. */
function storeDetailKeepingLocal(detail: PlanDetail, sentId: string) {
  const pending = state.outbox.filter((i) => i.planId === detail.id && i.kind === "patch" && i.id !== sentId) as Extract<OutboxItem, { kind: "patch" }>[];
  let merged = detail;
  for (const p of pending) merged = { ...merged, ...p.changes } as PlanDetail;
  const cur = state.details[detail.id];
  if (cur) merged = { ...merged, steps: cur.steps, progress: cur.progress } as PlanDetail;
  storeDetail(merged);
}

function handleRejected(item: OutboxItem, e: unknown) {
  if (item.kind === "patch" && e instanceof ApiError && e.code === "conflict") {
    const server = e.body.server as PlanDetail;
    const fields = (e.body.fields as (keyof PlanChanges)[]) ?? [];
    storeDetail(server);
    set({ conflicts: [...state.conflicts.filter((c) => c.planId !== item.planId), { planId: item.planId, fields, mine: item.changes, server }] });
    // Re-apply this patch's non-conflicting fields on top of the server copy.
    const rest = Object.fromEntries(Object.entries(item.changes).filter(([k]) => !fields.includes(k as keyof PlanChanges))) as PlanChanges;
    if (Object.keys(rest).length) enqueue({ id: uuid(), kind: "patch", planId: item.planId, base: server.version, changes: rest });
    return;
  }
  if (item.kind === "create" && e instanceof ApiError) {
    const { [item.planId]: _gone, ...rest } = state.plans;
    set({ plans: rest });
  }
  if (e instanceof ApiError && e.status === 404) {
    // The plan was deleted elsewhere: drop it locally.
    const { [item.planId]: _gone, ...rest } = state.plans;
    set({ plans: rest });
  }
  toast(t("err.dropped", { reason: errorText(e) }), { tone: "error" });
  void loadPlans();
}

export function resolveConflict(planId: string, keepMine: (keyof PlanChanges)[]) {
  const c = state.conflicts.find((x) => x.planId === planId);
  set({ conflicts: state.conflicts.filter((x) => x.planId !== planId) });
  if (!c) return;
  const changes = Object.fromEntries(keepMine.map((f) => [f, c.mine[f]])) as PlanChanges;
  if (Object.keys(changes).length) {
    patchLocal(planId, changes);
    enqueue({ id: uuid(), kind: "patch", planId, base: c.server.version, changes });
  }
}

// ---- workflow (online only) -----------------------------------------------------------

/** Makes sure nothing for this plan is still queued before a server-side state change. */
export async function settle(planId: string): Promise<boolean> {
  await flush();
  if (pendingFor(planId)) {
    toast(t("confirm.flushFirst"), { tone: "error" });
    return false;
  }
  return true;
}

export async function planAction(planId: string, action: "submit" | "approve" | "reject" | "reopen" | "cancel", body: unknown = {}) {
  if (!(await settle(planId))) return undefined;
  const detail = await online(() => api.post<PlanDetail>(`/api/plans/${planId}/${action}`, body));
  if (detail) {
    storeDetail(detail);
    void loadStats();
  }
  return detail;
}

/** Local-only update of display fields that have no request of their own (e.g. the approver's name). */
export function patchDetail(id: string, changes: Partial<PlanDetail>) {
  patchLocal(id, changes);
}

/** Adds or removes a just-uploaded attachment in the cached detail. */
export function setAttachments(id: string, attachments: PlanDetail["attachments"]) {
  const d = state.details[id];
  if (d) set({ details: { ...state.details, [id]: { ...d, attachments } } });
}
