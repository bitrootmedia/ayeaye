/**
 * The wire shapes, and the permission helpers that go with them.
 *
 * **The UI never re-derives the rules.** Every organisation arrives with the
 * caller's own `role` resolved server-side, and components branch on the
 * helpers below. A second copy of the rank comparison in a component is how
 * the button and the endpoint end up disagreeing — and the version the user
 * sees is always the wrong one to trust.
 *
 * These mirror `services/organisations.py`. If a rule changes there, it
 * changes here, and the API stays the thing that actually enforces it.
 */

export type Role = "member" | "admin" | "owner";
export type MemberStatus = "invited" | "active" | "disabled";

export const ROLE_RANK: Record<Role, number> = { member: 0, admin: 1, owner: 2 };

export const ROLE_LABEL: Record<Role, string> = {
  member: "Member",
  admin: "Admin",
  owner: "Owner",
};

export const ROLE_HELP: Record<Role, string> = {
  member: "Sees the organisation and whatever is shared with them.",
  admin: "Can do anything inside the organisation, including managing people.",
  owner: "Everything an admin can do, plus deleting the organisation.",
};

export type Organisation = {
  id: string;
  name: string;
  slug: string;
  /** The caller's role, resolved server-side. */
  role: Role;
  /** Unions with a member's own TOTP enrollment rather than replacing it —
   *  see services/mfa.py's account_requires_mfa. */
  require_mfa: boolean;
  created_at: string;
};

export type Member = {
  id: string;
  role: Role;
  status: MemberStatus;
  user_id: string | null;
  email: string | null;
  display_name: string | null;
  invited_by: string | null;
  accepted_at: string | null;
  created_at: string;
  /** Only ever sent to someone who could re-issue it anyway. */
  invite_url: string | null;
};

export type PendingInvite = {
  id: string;
  organisation_id: string;
  organisation_name: string;
  role: Role;
  invited_by: string | null;
  created_at: string;
};

export type InviteCreated = {
  member: Member;
  invite_url: string;
  /** False just means this deployment has no SMTP — copy the link instead. */
  emailed: boolean;
};

// --- projects and access -----------------------------------------------------

/**
 * The caller's resolved level on a project, from the API. `owner` is never
 * stored — it's what owning the project or administering the organisation
 * resolves to. See services/access.py.
 */
export type AccessLevel = "read" | "write" | "owner";
/** Only these two can be granted. `owner` is a column, not a grant. */
export type GrantLevel = "read" | "write";

export const ACCESS_RANK: Record<AccessLevel, number> = { read: 0, write: 1, owner: 2 };

export const LEVEL_LABEL: Record<AccessLevel, string> = {
  read: "Can view",
  write: "Can edit",
  owner: "Owner",
};

export const canView = (level: AccessLevel) => ACCESS_RANK[level] >= 0;
export const canEdit = (level: AccessLevel) => ACCESS_RANK[level] >= ACCESS_RANK.write;
/** Share, revoke, rename, archive, delete, hand over. Owner-only by design. */
export const canAdminister = (level: AccessLevel) => ACCESS_RANK[level] >= ACCESS_RANK.owner;

export type Person = { id: string; email: string | null; display_name: string | null };

/** What to call someone in a list. Email is the fallback, never blank. */
export const personName = (p: Person | null | undefined) =>
  p?.display_name || p?.email || "Unknown";

export type Team = { id: string; name: string; member_count: number; created_at: string };
export type TeamDetail = Team & { members: Person[] };
export type ProjectGroup = { id: string; name: string; created_at: string };

export type Project = {
  id: string;
  name: string;
  description: string | null;
  project_group_id: string | null;
  project_group_name: string | null;
  owner: Person | null;
  archived: boolean;
  created_at: string;
  access: AccessLevel;
  /** The caller's own visible tasks on this project — not everyone sees the
   *  same number. Only accurate on the list; other endpoints send 0/0. */
  open_task_count: number;
  /** Open, and critical, urgent or high priority — combined into one number
   *  rather than three, same reasoning as the field's own docstring in
   *  access.py. */
  important_task_count: number;
};

export type Grant = {
  id: string;
  level: GrantLevel;
  user: Person | null;
  team: Team | null;
  created_at: string;
};

export type ProjectAccess = {
  owner: Person | null;
  grants: Grant[];
  /** Listed explicitly, never implied — they can see it whether or not
   *  anyone shared it. */
  organisation_admins: Person[];
  can_manage: boolean;
};

// --- tasks ---------------------------------------------------------------------

/**
 * The fixed status set. `TODO` is the landing spot for new work — if `ON HOLD`
 * were the default it would be the commonest status in the system and would
 * stop meaning "deliberately parked".
 *
 * There is no `done`. Finishing a task is **closing** it, which is a separate
 * field, so a task can be closed from any status — including `blocker`, which
 * is what actually happens when work is abandoned rather than finished.
 */
export type TaskStatus = "todo" | "in_progress" | "on_hold" | "review" | "blocker";

export const TASK_STATUSES: TaskStatus[] = [
  "todo",
  "in_progress",
  "review",
  "on_hold",
  "blocker",
];

export const STATUS_LABEL: Record<TaskStatus, string> = {
  todo: "To do",
  in_progress: "In progress",
  review: "In review",
  on_hold: "On hold",
  blocker: "Blocked",
};

/**
 * Colour lives in a dot, not a pill — see index.css. Exactly one red and one
 * amber across the whole scale, so red always means "this needs you".
 */
export const STATUS_DOT: Record<TaskStatus, string> = {
  todo: "bg-status-todo",
  in_progress: "bg-status-progress",
  review: "bg-status-review",
  on_hold: "bg-status-hold",
  blocker: "bg-status-blocker",
};

/**
 * Priority, most urgent first. `normal` is the default and the middle of the
 * range, so raising and lowering are equally easy.
 *
 * Rendered as a **direction glyph, not a coloured dot**: status already owns
 * the only red (blocked) and the only amber (in review), and a second dot
 * badge per card would stop red meaning "this needs you". Only the top two
 * take colour.
 */
export type TaskPriority = "critical" | "urgent" | "high" | "normal" | "low" | "very_low";

export const TASK_PRIORITIES: TaskPriority[] = [
  "critical",
  "urgent",
  "high",
  "normal",
  "low",
  "very_low",
];

export const PRIORITY_LABEL: Record<TaskPriority, string> = {
  critical: "Critical",
  urgent: "Urgent",
  high: "High",
  normal: "Normal",
  low: "Low",
  very_low: "Very low",
};

/** Shape carries the level; colour is spent only where it has to be. */
export const PRIORITY_TONE: Record<TaskPriority, string> = {
  critical: "text-status-blocker",
  urgent: "text-status-review",
  high: "text-muted-foreground",
  normal: "text-muted-foreground",
  low: "text-muted-foreground",
  very_low: "text-muted-foreground",
};

export const PRIORITY_RANK: Record<TaskPriority, number> = {
  critical: 6,
  urgent: 5,
  high: 4,
  normal: 3,
  low: 2,
  very_low: 1,
};

/** Fixed set, urgency-decreasing — same convention as PRIORITY_RANK: ordered
 *  by what it means, not by spelling. */
export type PlannerBucket = "today" | "tomorrow" | "this_week" | "next_week" | "someday";

export const PLANNER_BUCKETS: PlannerBucket[] = [
  "today",
  "tomorrow",
  "this_week",
  "next_week",
  "someday",
];

export const PLANNER_BUCKET_LABEL: Record<PlannerBucket, string> = {
  today: "Today",
  tomorrow: "Tomorrow",
  this_week: "This week",
  next_week: "Next week",
  someday: "Someday",
};

export type PlannerTask = {
  id: string;
  title: string;
  priority: TaskPriority;
  status: TaskStatus;
  is_open: boolean;
};

export type PlannerEntry = {
  task: PlannerTask;
  bucket: PlannerBucket;
  position: number;
};

export type PlannerBoard = {
  pool: PlannerTask[];
  buckets: Record<PlannerBucket, PlannerEntry[]>;
};

/**
 * A label in the organisation's shared vocabulary.
 *
 * `off_board` is the only one that changes behaviour: tasks carrying such a
 * tag leave the board and the list. They stay searchable and reachable by
 * filtering for the tag — the point is "this isn't queueing for attention",
 * not "hide this".
 */
export type Tag = {
  id: string;
  name: string;
  off_board: boolean;
  /** Only populated by the vocabulary endpoint. */
  task_count: number;
};

/** One item on a checklist. */
export type ChecklistItem = {
  id: string;
  text: string;
  done: boolean;
};

/** A quick todo list on a task — a task can carry more than one. */
export type Checklist = {
  id: string;
  title: string;
  items: ChecklistItem[];
};

/** One checked cell on a sheet. A cell's presence here IS the check — a
 *  (row, column) pair with no entry is unchecked. */
export type SheetCell = {
  row_id: string;
  column_id: string;
  checked_by: Person;
  checked_at: string;
};

export type SheetRow = {
  id: string;
  label: string;
};

export type SheetColumn = {
  id: string;
  label: string;
};

/** A grid checklist on a task — a task can carry more than one. Rows and
 *  columns are freeform labels; a cell is a checkbox at their intersection. */
export type Sheet = {
  id: string;
  title: string;
  rows: SheetRow[];
  columns: SheetColumn[];
  cells: SheetCell[];
};

export type Task = {
  id: string;
  title: string;
  description: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  /** Separate from status, and owner-controlled. */
  is_open: boolean;
  /** Hidden from everyone but the owner — so if you can read this, it's
   *  yours. See services/access.py: it short-circuits every other route. */
  is_hidden: boolean;
  /** The caller's own bookmark, not a property of the task — see
   *  services/pins.py. Two people looking at the same task can get two
   *  different answers here. */
  is_pinned: boolean;
  closed_at: string | null;
  project_id: string | null;
  project_name: string | null;
  owner: Person | null;
  action_required: Person | null;
  due_on: string | null;
  /** Both purely informational planning fields — neither feeds the access
   *  model, the board, or any sweep the way `due_on` does. */
  estimated_start_on: string | null;
  estimated_hours: number | null;
  position: number;
  created_at: string;
  /** **Last activity, not last row update.** A comment, a file, a tag, an
   *  hour logged — all bump it. A private note deliberately does not: a note
   *  nobody else can read must not announce itself through a timestamp
   *  everybody can see. */
  updated_at: string;
  access: AccessLevel;
  /** Resolved server-side: only the owner (or an org admin) may close. */
  can_close: boolean;
  /** Owner-only, and deliberately NOT the same rule as `can_close` — an
   *  organisation admin qualifies for that one and not for this. */
  can_hide: boolean;
  /** Set only when this task is part of a recurring series. `null` on the
   *  list and board views — see services/recurrence.py. */
  recurrence: TaskRecurrence | null;
  /** The caller's own day-planner bucket for this task — personal, like
   *  `is_pinned`, and `null` on the list and board views for the same
   *  reason `recurrence` is. `null` here means unplanned, not "unknown". */
  planner_bucket: PlannerBucket | null;
  tags: Tag[];
};

/** A recurring task's cadence. On schedule, not on close — the next
 *  occurrence appears whether or not this one is done. */
export type TaskRecurrence = {
  id: string;
  interval_unit: "day" | "week" | "month";
  interval_count: number;
  next_due_on: string;
  active: boolean;
  /** Resolved server-side: whoever set it up, or an organisation admin. */
  can_manage: boolean;
};

/** One board column: what's shown, and how much there really is. */
export type BoardColumn = {
  key: string;
  /** The column's real size. `tasks.length` is only the page. */
  total: number;
  tasks: Task[];
};

export type BoardData = {
  group_by: "status" | "priority" | "action_required";
  per_group: number;
  columns: BoardColumn[];
};

export type TaskEvent = {
  id: string;
  kind: string;
  actor: Person | null;
  data: Record<string, unknown>;
  created_at: string;
};

export type TaskAccess = {
  owner: Person | null;
  action_required: Person | null;
  project_name: string | null;
  inherits_from_project: boolean;
  grants: Grant[];
  organisation_admins: Person[];
  can_manage: boolean;
};

/** One task, on the calendar. Team-wide — every task you can see with a due
 *  date in the visible window, not narrowed to yours. */
export type CalendarTask = {
  id: string;
  title: string;
  due_on: string;
  status: TaskStatus;
  priority: TaskPriority;
  project_name: string | null;
};

/** One reminder, on the calendar. Private — see services/reminders.py; two
 *  people looking at the same month see different reminder dots. NULL
 *  `task_id` means a standalone reminder — `title` is its own "what" then. */
export type CalendarReminder = {
  id: string;
  remind_on: string;
  note: string | null;
  task_id: string | null;
  task_title: string | null;
  title: string | null;
};

/** One out-of-office period, on the calendar. Team-wide, not private — see
 *  services/presence.py: "its whole value is a colleague checking before
 *  they ask you for something." Spans a range, unlike a task's due date or a
 *  reminder's single day. */
export type CalendarAbsence = {
  id: string;
  person: Person | null;
  starts_on: string;
  ends_on: string;
  note: string | null;
};

export type CalendarData = {
  tasks: CalendarTask[];
  reminders: CalendarReminder[];
  away: CalendarAbsence[];
};

/** A notepad entry. Personal, like a reminder — there is no "whose" field
 *  because there is only ever one answer, and no admin override anywhere. */
export type PersonalNote = {
  id: string;
  title: string;
  body: string;
  created_at: string;
  updated_at: string;
};

/** A reminder. Personal — there is no "whose" field because there is only
 *  ever one answer. */
export type Reminder = {
  id: string;
  remind_on: string;
  note: string | null;
  /** Resolved server-side against your own timezone: whether "today" has
   *  arrived is not a question the browser can answer for a reminder set on
   *  a phone in another country. */
  overdue: boolean;
  /** NULL for a standalone reminder — `title` is its own "what" then. */
  task_id: string | null;
  task_title: string | null;
  title: string | null;
  organisation_id: string | null;
  organisation_name: string | null;
};

/** A stretch of days somebody is away. Deliberately not private — the whole
 *  value is that a colleague checks before asking you for something. */
export type Absence = {
  id: string;
  starts_on: string;
  ends_on: string;
  note: string | null;
  person: Person | null;
  /** Away today, as opposed to away somewhere in the next fortnight. */
  away_now: boolean;
};

/** One hour of one weekday somebody plans to be around. `weekday` is
 *  0=Monday..6=Sunday, matching Python's own `date.weekday()` server-side. */
export type WorkingHourCell = { weekday: number; hour: number };

export type WorkingHours = {
  /** IANA, or `null` for someone who has never opened the app. */
  timezone: string | null;
  cells: WorkingHourCell[];
};

/** A quick capture — an idea, a link, a note-to-self. Cross-organisation
 *  and yours alone; see the "Sparks" section in CLAUDE.md. */
export type Spark = {
  id: string;
  body: string;
  created_at: string;
  updated_at: string;
};

export type Announcement = {
  id: string;
  body: string;
  sticky: boolean;
  expires_on: string | null;
  author: Person | null;
  created_at: string;
};

/** One row on a dashboard escalation card — Critical, Urgent, Due soon,
 *  Pinned. `is_action_required` and `waiting_on` are the distinction those
 *  cards exist to draw: one needs me, the other needs someone else.
 *  `is_overdue`/`is_due_today` are computed server-side against the
 *  viewer's own timezone, the same "today" the whole dashboard resolves
 *  once. */
export type DashboardTask = {
  id: string;
  title: string;
  status: string;
  project_id: string | null;
  project_name: string | null;
  due_on: string | null;
  is_owner: boolean;
  is_action_required: boolean;
  waiting_on: Person | null;
  is_overdue: boolean;
  is_due_today: boolean;
};

/** One row of "what changed" — organisation-wide, not narrowed to the
 *  caller's own work. Sorted by `updated_at`, which a comment bumps just
 *  like a status change does. */
export type RecentTask = {
  id: string;
  title: string;
  status: string;
  project_id: string | null;
  project_name: string | null;
  owner: Person | null;
  is_open: boolean;
  updated_at: string;
};

/** One request, because a landing page that renders in three stages looks
 *  broken. */
export type DashboardData = {
  announcements: Announcement[];
  away: Absence[];
  /** Resolved server-side — admins write, everyone reads. */
  can_announce: boolean;
  critical: DashboardTask[];
  urgent: DashboardTask[];
  high: DashboardTask[];
  due_soon: DashboardTask[];
  pinned: DashboardTask[];
  recent: RecentTask[];
};

/** A personal access token. The secret is only ever in the create response. */
export type AccessToken = {
  id: string;
  name: string;
  scope: "read" | "write";
  prefix: string;
  last_used_at: string | null;
  created_at: string;
};

export type Notification = {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  link_path: string | null;
  read_at: string | null;
  created_at: string;
};

export type ExportStatus = "pending" | "ready" | "failed" | "expired";

export type Export = {
  id: string;
  project_id: string | null;
  status: ExportStatus;
  file_size: number | null;
  created_at: string;
  completed_at: string | null;
};

// --- organisation roles -------------------------------------------------------

export const canManageMembers = (role: Role) => ROLE_RANK[role] >= ROLE_RANK.admin;
export const canRename = (role: Role) => ROLE_RANK[role] >= ROLE_RANK.admin;
export const canDeleteOrg = (role: Role) => role === "owner";
export const canRequireMfa = (role: Role) => ROLE_RANK[role] >= ROLE_RANK.admin;

/** You cannot appoint someone above yourself. */
export const grantableRoles = (actor: Role): Role[] =>
  canManageMembers(actor)
    ? (Object.keys(ROLE_RANK) as Role[]).filter((r) => ROLE_RANK[r] <= ROLE_RANK[actor])
    : [];

/** You cannot act on someone ranked above you. Equal rank is allowed. */
export const canActOn = (actor: Role, subject: Role) => ROLE_RANK[actor] >= ROLE_RANK[subject];

/** One search result. `kind` decides the icon and the link. */
export type SearchHit = {
  kind: "task" | "project" | "note";
  id: string;
  title: string;
  /** A window around the match, so a hit deep in a description shows why. */
  subtitle: string | null;
  /** Where it lives — a task's project, for instance. */
  context: string | null;
  score: number;
  /** Closed or archived. Shown, struck through, not hidden. */
  inactive: boolean;
};

/** One dependency edge. `task` is `null` when the other side is invisible to
 *  the caller — task-level access can differ between two people looking at
 *  the same edge, and this never leaks a title or status past that. */
export type TaskDependency = {
  id: string;
  task: { id: string; title: string; status: TaskStatus; is_open: boolean } | null;
};

export type TaskDependencies = {
  /** What this task is waiting on — the edit surface. */
  depends_on: TaskDependency[];
  /** What's waiting on this task — read-only here; edited from that task's
   *  own list instead. */
  blocks: TaskDependency[];
};

/** Where a notification actually goes. Email always exists — provisioned on
 *  first read — and is the only kind that can't be deleted, only narrowed. */
export type NotificationChannel = {
  id: string;
  kind: "email" | "telegram" | "webhook";
  label: string;
  enabled_kinds: string[];
  /** `null` for a Telegram link nobody has tapped `/start` on yet. */
  verified_at: string | null;
  created_at: string;
  /** The webhook's own URL. `null` for email and Telegram. */
  url: string | null;
  /** Where a linked Telegram chat's `/task` files new tasks. Set from
   *  inside Telegram via `/org`, never from here — read-only display. `null`
   *  for email and webhook, and for a Telegram link with no default yet. */
  default_organisation_id: string | null;
};

/** The closed `NOTIFICATION_KINDS` set, human-labelled for the routing
 *  matrix — the inbox itself renders every kind uniformly and never needed
 *  one of these. */
export const NOTIFICATION_KIND_LABEL: Record<string, string> = {
  task_action_required: "Asked to act on a task",
  task_action_required_cleared: "Handed back to you",
  task_owner_changed: "Given ownership of a task",
  task_closed: "A task you own was closed",
  task_shared: "A task was shared with you",
  project_shared: "A project was shared with you",
  reminder_soon: "Reminder, the day before",
  reminder_due: "Reminder, on the day",
  task_deadline_tomorrow: "A task is due tomorrow",
  daily_summary: "Daily summary",
  export_ready: "A data export finished",
};

// --- time ------------------------------------------------------------------

export type TimeEntry = {
  id: string;
  task_id: string;
  task_title: string | null;
  project_name: string | null;
  user: Person | null;
  started_at: string;
  /** null means running — the client ticks the elapsed value itself. */
  ended_at: string | null;
  seconds: number;
  note: string | null;
  edited_at: string | null;
};

export type Timer = { entry: TimeEntry | null; organisation_id: string | null };

export type RollupRow = { id: string | null; name: string; seconds: number };
export type TimeSummary = {
  total_seconds: number;
  by_person: RollupRow[];
  by_project: RollupRow[];
  by_task: RollupRow[];
};

/** `5400 -> "1h 30m"`. Mirrors `format_duration` in services/time_tracking.py. */
export function formatDuration(seconds: number): string {
  const totalMinutes = Math.floor(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours && minutes) return `${hours}h ${minutes}m`;
  if (hours) return `${hours}h`;
  return `${minutes}m`;
}

/** A running timer, to the second — `1:04:09`. */
export function formatClock(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/**
 * Turn what someone types into minutes. `"1h30"`, `"90"`, `"1.5h"`, `"45m"`.
 *
 * People type durations a dozen ways and a form that only accepts one of them
 * is a form people stop using. A bare number means minutes, because that is
 * what "30" means to someone logging time.
 */
export function parseDuration(input: string): number | null {
  const text = input.trim().toLowerCase().replace(/\s+/g, "");
  if (!text) return null;

  const hm = text.match(/^(\d+(?:[.,]\d+)?)h(\d+)?m?$/);
  if (hm) {
    const hours = parseFloat(hm[1].replace(",", "."));
    return Math.round(hours * 60) + (hm[2] ? parseInt(hm[2], 10) : 0);
  }
  const mOnly = text.match(/^(\d+)m$/);
  if (mOnly) return parseInt(mOnly[1], 10);
  const bare = text.match(/^\d+$/);
  if (bare) return parseInt(text, 10);
  return null;
}


/** One file on a task, however it arrived. */
export type TaskFile = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  url: string;
  /** null until the worker has made one, or for anything that isn't an image. */
  thumbnail_url: string | null;
  /** True when it came in through a comment rather than the Files panel. */
  from_comment: boolean;
  uploaded_by: Person | null;
  created_at: string;
};
