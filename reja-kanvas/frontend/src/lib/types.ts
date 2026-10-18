export type Lang = "uz" | "uz-Cyrl" | "ru" | "en";
export type Color = "yellow" | "mint" | "lilac" | "peach" | "sky" | "white";
export type PlanStatus = "active" | "pending_approval" | "returned" | "done" | "cancelled";
export type StepStatus = "todo" | "done" | "cancelled";
export type Rating = "excellent" | "good" | "partial";
export type Role = "owner" | "approver" | "backup" | "team" | "viewer";
export type Priority = "low" | "normal" | "high" | "urgent";

export interface Recurrence {
  freq: "daily" | "weekly" | "monthly";
  interval: number;
  weekdays: number[];
  until: string | null;
}

export interface Prefs {
  email_kinds: string[];
  digest: boolean;
  quiet_start: string | null;
  quiet_end: string | null;
  large_text: boolean;
  high_contrast: boolean;
  onboarded: boolean;
}

export interface User {
  id: string;
  email: string;
  name: string;
  tz: string;
  lang: Lang;
  created_at: string;
  totp_enabled?: boolean;
  prefs?: Partial<Prefs>;
}

export interface Person {
  id: string;
  name: string;
  email: string;
}

export interface Progress {
  done: number;
  total: number;
  cancelled: number;
}

export interface Plan {
  id: string;
  title: string;
  tag: string | null;
  color: Color;
  x: number;
  y: number;
  due_at: string | null;
  remind_minutes: number | null;
  goal: string;
  done_criteria: string;
  require_proof: boolean;
  status: PlanStatus;
  submitted_at: string | null;
  completed_at: string | null;
  approved_at: string | null;
  late_minutes: number | null;
  rating: Rating | null;
  final_note: string | null;
  return_reason: string | null;
  escalated_at: string | null;
  version: number;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  owner_id: string;
  approver_id: string | null;
  backup_approver_id: string | null;
  progress: Progress;
  priority: Priority;
  recurrence: Recurrence | null;
  series_id: string | null;
  next_occurrence_id: string | null;
  archived_at: string | null;
  tracked_seconds: number;
  timer_started_at: string | null;
  blocked_by: string[];
  parent_id: string | null;
  duration_minutes: number | null;
  goal_id: string | null;
  board_id: string | null;
  approval_stage: number;
  approval_chain: string[];
  my_role?: Role | null;
  can_decide?: boolean;
  purge_at?: string;
  owner?: Person | null;
}

export interface Step {
  id: string;
  text: string;
  status: StepStatus;
  position: number;
  done_at: string | null;
  due_at?: string | null;
  assignee_id?: string | null;
}

export interface Attachment {
  id: string;
  filename: string;
  mime: string;
  size: number;
  created_at: string;
  inline?: boolean;
  url?: string;
}

export interface PlanDetail extends Plan {
  body_html: string;
  steps: Step[];
  attachments: Attachment[];
  owner: Person | null;
  approver: Person | null;
  backup_approver: Person | null;
  approved_by: Person | null;
  blockers?: string[];
  open_blockers?: { id: string; title: string; status: PlanStatus }[];
  chain?: (Person | null)[];
  current_approver?: Person | null;
  children?: { id: string; title: string; status: PlanStatus; due_at: string | null }[];
  parent?: { id: string; title: string } | null;
  signatures?: { role: string; image: string; signed_at: string; user_name: string | null }[];
}

/** Fields a client may change with PATCH /plans/:id. */
export type PlanChanges = Partial<
  Pick<
    PlanDetail,
    | "title" | "body_html" | "tag" | "color" | "x" | "y" | "due_at" | "remind_minutes"
    | "goal" | "done_criteria" | "require_proof" | "approver_id" | "backup_approver_id" | "priority" | "recurrence"
    | "parent_id" | "goal_id" | "duration_minutes" | "approval_chain"
  >
>;

export interface Stats {
  today: string;
  today_total: number;
  today_done: number;
  streak: number;
  freeze_used_this_week: boolean;
  awaiting_my_approval: number;
  unread_notifications: number;
}

export interface PlanEvent {
  id: number;
  kind: string;
  data: Record<string, unknown>;
  created_at: string;
  user_name: string | null;
}

export interface Notification {
  id: number;
  plan_id: string | null;
  kind: string;
  data: { title?: string; reason?: string; due_at?: string; has_backup?: boolean };
  read_at: string | null;
  created_at: string;
}

export interface ShareLink {
  token: string;
  role: "view" | "edit";
  expires_at: string;
  revoked_at: string | null;
  created_at?: string;
}

export interface SharedPlan extends Omit<PlanDetail, "attachments" | "approver" | "backup_approver" | "approved_by"> {
  share_role: "view" | "edit";
  share_expires_at: string;
}

export interface Conflict {
  planId: string;
  fields: (keyof PlanChanges)[];
  mine: PlanChanges;
  server: PlanDetail;
}

export interface Comment {
  id: string;
  plan_id: string;
  user_id: string | null;
  user_name: string | null;
  body: string;
  created_at: string;
  edited_at: string | null;
  reactions?: { emoji: string; count: number; mine: boolean }[];
}

export interface ParsedPlan {
  title: string;
  due_at: string | null;
  tag: string | null;
  priority: Priority | null;
  recurrence: Recurrence | null;
}

export interface Analytics {
  days: number;
  series: { date: string; done: number; created: number }[];
  total_done: number;
  total_created: number;
  open_now: number;
  overdue_now: number;
  on_time: number;
  late: number;
  on_time_rate: number | null;
  avg_late_minutes: number | null;
  weekday_done: number[];
  by_tag: { tag: string; done: number; open: number }[];
  by_priority: Record<Priority, number>;
  tracked_by_tag: { tag: string; seconds: number }[];
  tracked_total: number;
  streak: number;
  best_streak: number;
}

export interface TemplateInfo {
  key: string;
  count: number;
  name?: string;
}

export type TeamRole = "owner" | "admin" | "member" | "viewer";

export interface Board {
  id: string | null;
  name: string | null;
  team_id: string | null;
  team_name: string | null;
  role: TeamRole;
}

export interface Team {
  id: string;
  name: string;
  created_at: string;
  my_role: TeamRole;
  members: (Person & { role: TeamRole; joined_at: string })[];
}

export interface Goal {
  id: string;
  title: string;
  description: string;
  target_date: string | null;
  color: Color;
  archived_at: string | null;
  created_at: string;
  plans_total: number;
  plans_done: number;
  progress: number;
}

export interface FilterQuery {
  text: string;
  tags: string[];
  priorities: Priority[];
  statuses: PlanStatus[];
  due: "overdue" | "today" | "week" | "none" | null;
  mine_only: boolean;
}

export interface SavedFilter {
  id: string;
  name: string;
  query: FilterQuery;
}

export interface CanvasItem {
  id: string;
  board_id: string | null;
  kind: "note" | "frame";
  x: number;
  y: number;
  w: number;
  h: number;
  text: string;
  color: Color;
  created_at: string;
  updated_at: string;
}

export interface TimeEntry {
  id: number;
  started_at: string;
  ended_at: string;
  seconds: number;
  note: string;
  manual: number;
  user_name: string | null;
}

export interface Session {
  id: string;
  user_agent: string;
  ip: string;
  created_at: string;
  last_seen_at: string;
  current: boolean;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  key?: string;
}

export interface Webhook {
  id: string;
  url: string;
  events: string[];
  active: boolean;
  failures: number;
  last_status: string | null;
  created_at: string;
  secret?: string;
}

export interface MyStep {
  id: string;
  text: string;
  status: StepStatus;
  due_at: string | null;
  plan_id: string;
  plan_title: string;
}
