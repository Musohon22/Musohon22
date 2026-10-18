export type Lang = "uz" | "uz-Cyrl" | "ru" | "en";
export type Color = "yellow" | "mint" | "lilac" | "peach" | "sky" | "white";
export type PlanStatus = "active" | "pending_approval" | "returned" | "done" | "cancelled";
export type StepStatus = "todo" | "done" | "cancelled";
export type Rating = "excellent" | "good" | "partial";
export type Role = "owner" | "approver" | "backup";

export interface User {
  id: string;
  email: string;
  name: string;
  tz: string;
  lang: Lang;
  created_at: string;
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
}

export interface Attachment {
  id: string;
  filename: string;
  mime: string;
  size: number;
  created_at: string;
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
}

/** Fields a client may change with PATCH /plans/:id. */
export type PlanChanges = Partial<
  Pick<
    PlanDetail,
    | "title" | "body_html" | "tag" | "color" | "x" | "y" | "due_at" | "remind_minutes"
    | "goal" | "done_criteria" | "require_proof" | "approver_id" | "backup_approver_id"
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
