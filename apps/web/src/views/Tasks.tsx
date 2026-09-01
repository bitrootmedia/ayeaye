import {
  ArrowDownIcon,
  ArrowUpIcon,
  CircleDotIcon,
  Columns3Icon,
  EyeOffIcon,
  LayoutGridIcon,
  ListIcon,
  PlusIcon,
  SignalIcon,
  UserCheckIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useOutletContext, useParams, useSearchParams } from "react-router-dom";

import { api, apiWithHeaders } from "@/api";
import type { Shell } from "@/App";
import { useRealtime } from "@/hooks/use-realtime";
import { EntityPicker, type PickerItem } from "@/components/entity-picker";
import { NewTaskDialog } from "@/components/new-task-dialog";
import { PageHeader } from "@/components/page-header";
import { PriorityGlyph } from "@/components/priority";
import { ClosedBadge, StatusBadge } from "@/components/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TagChip } from "@/components/tag-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { ago, timestamp } from "@/lib/format";
import { lastView, rememberView } from "@/lib/view-preference";
import {
  PRIORITY_LABEL,
  STATUS_LABEL,
  TASK_PRIORITIES,
  TASK_STATUSES,
  personName,
  type BoardData,
  type Member,
  type Project,
  type Tag,
  type Task,
  type TaskPriority,
  type TaskStatus,
} from "@/lib/types";

const NO_PROJECT = "__loose__";

/** List rows per page, and how much "Show more" adds. */
const PAGE = 100;

type GroupBy = "status" | "priority" | "action_required";

/**
 * How long the board waits before refetching after a live event.
 *
 * The task screen refetches immediately — one task, one small response. A
 * board is the opposite: it shows everything and a busy organisation produces
 * a steady trickle of changes, so it collects them into one refresh. Skipped
 * entirely when the tab is hidden; the next visible event catches up.
 */
const LIVE_COALESCE_MS = 1_500;

/**
 * The board.
 *
 * Columns are statuses; **closed is not one of them**. A closed task keeps
 * whatever status it had, so putting "Closed" at the end of the board would
 * throw that away and make it look like a sixth status. Closed work is behind
 * a toggle instead, and shows with its real status plus a Closed badge.
 *
 * The columns can be **priorities instead**. Those are the two questions a
 * board gets asked — "where is everything up to" and "what should I do next" —
 * and they want the same cards arranged differently, not two screens. It's a
 * view setting in the URL, so a link carries the arrangement you meant.
 */
export default function Tasks() {
  const { orgId } = useParams<{ orgId: string }>();
  const { organisations } = useOutletContext<Shell>();
  const [params, setParams] = useSearchParams();
  const org = organisations.find((o) => o.id === orgId) ?? null;

  const projectFilter = params.get("project");
  const tagFilter = params.get("tag");
  // The URL wins when it names a view explicitly (a link somebody sends
  // carries the view they meant); otherwise fall back to whatever you
  // last toggled to here, rather than always defaulting to Board.
  const viewParam = params.get("view");
  const view: "list" | "board" =
    viewParam === "list" || viewParam === "board"
      ? viewParam
      : lastView("tasks") === "list"
        ? "list"
        : "board";
  const groupParam = params.get("group");
  const groupBy: GroupBy =
    groupParam === "priority"
      ? "priority"
      : groupParam === "action_required"
        ? "action_required"
        : "status";
  // Sorting and filtering live in the URL, so a view somebody arrived at is a
  // view they can send to a colleague.
  const sort = params.get("sort");
  const descending = params.get("dir") === "desc";
  const statusFilter = params.get("status");
  const priorityFilter = params.get("priority");
  const ownerFilter = params.get("owner");
  const actionFilter = params.get("needs");
  const showClosed = params.get("closed") === "1";

  const [board, setBoard] = useState<BoardData | null>(null);
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [listTotal, setListTotal] = useState(0);
  const [projects, setProjects] = useState<Project[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [creating, setCreating] = useState(false);
  // How many list rows to ask for. Grows on "Show more" rather than appending
  // pages: re-asking for a bigger window is one code path, and it can't drift
  // out of order when something changes underneath.
  const [listLimit, setListLimit] = useState(PAGE);
  const refresh = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const filters = useCallback(() => {
    const query = new URLSearchParams({ include_closed: String(showClosed) });
    if (projectFilter === NO_PROJECT) query.set("loose", "true");
    else if (projectFilter) query.set("project_id", projectFilter);
    // Asking for a tag by name is asking for its tasks, off-board or not.
    if (tagFilter) query.set("tag_id", tagFilter);
    if (statusFilter) query.set("status", statusFilter);
    if (priorityFilter) query.set("priority", priorityFilter);
    if (ownerFilter) query.set("owner_user_id", ownerFilter);
    if (actionFilter) query.set("action_required_user_id", actionFilter);
    return query;
  }, [projectFilter, tagFilter, showClosed, statusFilter, priorityFilter, ownerFilter, actionFilter]);

  const load = useCallback(async () => {
    if (!orgId) return;
    const query = filters();
    const [ps, gs, ms] = await Promise.all([
      api<Project[]>(`/organisations/${orgId}/projects`),
      api<Tag[]>(`/organisations/${orgId}/tags`),
      api<Member[]>(`/organisations/${orgId}/members`),
    ]);
    setProjects(ps);
    setTags(gs);
    setMembers(ms);

    if (view === "board") {
      // The board is bounded per column server-side — a `LIMIT` can't do it,
      // because the rows arrive priority-first and four columns would come
      // back empty. See services/access.py:board_stmt.
      query.set("group", groupBy);
      setBoard(await api<BoardData>(`/organisations/${orgId}/tasks/board?${query}`));
    } else {
      if (sort) {
        query.set("sort", sort);
        query.set("dir", descending ? "desc" : "asc");
      }
      query.set("limit", String(listLimit));
      const res = await apiWithHeaders<Task[]>(`/organisations/${orgId}/tasks?${query}`);
      setTasks(res.data);
      setListTotal(Number(res.headers.get("X-Total-Count") ?? res.data.length));
    }
  }, [orgId, filters, view, groupBy, listLimit, sort, descending]);

  useEffect(() => {
    void load().catch(() => {
      setTasks([]);
      setBoard({ group_by: groupBy, per_group: 0, columns: [] });
    });
  }, [load, groupBy]);

  // Live. Every task change publishes on the socket; this screen shows many
  // tasks at once, so it coalesces rather than refetching per event — twenty
  // people working means twenty events a second and one board is a real
  // payload however well it is bounded.
  useRealtime(
    useCallback(
      (event) => {
        if (event.type !== "task") return;
        if (refresh.current) clearTimeout(refresh.current);
        refresh.current = setTimeout(() => {
          if (document.visibilityState === "visible") void load();
        }, LIVE_COALESCE_MS);
      },
      [load],
    ),
    // The board watches its organisation rather than every card on it.
    useMemo(() => (orgId ? { kind: "org" as const, id: orgId } : undefined), [orgId]),
  );

  if (!org) return null;

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  };

  const filterItems: PickerItem[] = [
    { value: NO_PROJECT, label: "No project (loose)" },
    ...projects.map((p) => ({
      value: p.id,
      label: p.name,
      hint: p.project_group_name ?? undefined,
    })),
  ];

  const tagItems: PickerItem[] = tags.map((t) => ({
    value: t.id,
    label: t.name,
    hint: t.off_board ? "kept off the board" : undefined,
  }));
  const offBoardTag = tags.find((t) => t.id === tagFilter && t.off_board) ?? null;
  const people: PickerItem[] = members
    .filter((m) => m.status === "active" && m.user_id)
    .map((m) => ({
      value: m.user_id!,
      label: m.display_name || m.email || "Unknown",
      hint: m.display_name ? (m.email ?? undefined) : undefined,
    }));
  const empty =
    view === "board"
      ? (board?.columns.length ?? 0) === 0
      : (tasks?.length ?? 0) === 0;

  return (
    <>
      <PageHeader
        crumbs={[{ label: org.name, to: `/orgs/${org.id}` }, { label: "Tasks" }]}
        title="Tasks"
        description="What you can see: your own, plus anything shared with you or a team you're in."
        actions={
          <>
            <Button variant="ghost" onClick={() => setParam("closed", showClosed ? null : "1")}>
              <EyeOffIcon />
              {showClosed ? "Hide closed" : "Show closed"}
            </Button>
            {view === "board" && (
              <Button
                variant="ghost"
                aria-label="Group the board by status, priority, or action required"
                onClick={() =>
                  setParam(
                    "group",
                    groupBy === "status"
                      ? "priority"
                      : groupBy === "priority"
                        ? "action_required"
                        : null,
                  )
                }
              >
                {groupBy === "status" ? (
                  <SignalIcon />
                ) : groupBy === "priority" ? (
                  <UserCheckIcon />
                ) : (
                  <Columns3Icon />
                )}
                {groupBy === "status"
                  ? "By priority"
                  : groupBy === "priority"
                    ? "By action required"
                    : "By status"}
              </Button>
            )}
            <Button
              variant="ghost"
              onClick={() => {
                const next = view === "board" ? "list" : "board";
                setParam("view", next);
                rememberView("tasks", next);
              }}
            >
              {view === "board" ? <ListIcon /> : <LayoutGridIcon />}
              {view === "board" ? "List" : "Board"}
            </Button>
            <Button onClick={() => setCreating(true)}>
              <PlusIcon />
              New task
            </Button>
          </>
        }
      />

      <div className="flex flex-wrap gap-2">
        <div className="w-full max-w-xs">
          <EntityPicker
            ariaLabel="Filter by project"
            items={filterItems}
            value={projectFilter}
            placeholder="All projects"
            emptyLabel="All projects"
            searchPlaceholder="Find a project…"
            onChange={(v) => setParam("project", v)}
          />
        </div>
        {tags.length > 0 && (
          <div className="w-full max-w-xs">
            <EntityPicker
              ariaLabel="Filter by tag"
              items={tagItems}
              value={tagFilter}
              placeholder="All tags"
              emptyLabel="All tags"
              searchPlaceholder="Find a tag…"
              onChange={(v) => setParam("tag", v)}
            />
          </div>
        )}
        {/* The rest only in the list. On a board, status *is* the columns —
            filtering by one would leave a board with a single column, which
            is a list drawn badly. */}
        {view === "list" && (
          <>
            <div className="w-44">
              <EntityPicker
                ariaLabel="Filter by status"
                items={TASK_STATUSES.map((s) => ({ value: s, label: STATUS_LABEL[s] }))}
                value={statusFilter}
                placeholder="Any status"
                emptyLabel="Any status"
                searchPlaceholder="Filter…"
                onChange={(v) => setParam("status", v)}
              />
            </div>
            <div className="w-44">
              <EntityPicker
                ariaLabel="Filter by priority"
                items={TASK_PRIORITIES.map((p) => ({
                  value: p,
                  label: PRIORITY_LABEL[p],
                  icon: <PriorityGlyph priority={p} />,
                }))}
                value={priorityFilter}
                placeholder="Any priority"
                emptyLabel="Any priority"
                searchPlaceholder="Filter…"
                onChange={(v) => setParam("priority", v)}
              />
            </div>
            <div className="w-52">
              <EntityPicker
                ariaLabel="Filter by owner"
                items={people}
                value={ownerFilter}
                placeholder="Any owner"
                emptyLabel="Any owner"
                searchPlaceholder="Find a person…"
                onChange={(v) => setParam("owner", v)}
              />
            </div>
            <div className="w-52">
              <EntityPicker
                ariaLabel="Filter by who must act"
                items={people}
                value={actionFilter}
                placeholder="Anyone to act"
                emptyLabel="Anyone to act"
                searchPlaceholder="Find a person…"
                onChange={(v) => setParam("needs", v)}
              />
            </div>
          </>
        )}
      </div>

      {/* Off-board tasks are absent unless you asked for one by name, so the
          screen says which mode it's in rather than leaving a silent gap. */}
      {offBoardTag && (
        <p className="text-sm text-muted-foreground">
          Showing <span className="font-medium text-foreground">{offBoardTag.name}</span>, which is
          kept off the board. These don&rsquo;t appear in the normal view.
        </p>
      )}

      {(view === "board" ? board === null : tasks === null) ? (
        <div className="flex flex-1 items-center justify-center py-12">
          <Spinner />
        </div>
      ) : empty ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <CircleDotIcon />
            </EmptyMedia>
            <EmptyTitle>No tasks here</EmptyTitle>
            <EmptyDescription>
              You see tasks you own, ones you&rsquo;ve been asked to act on, and anything in a
              project shared with you. There may be others you can&rsquo;t.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => setCreating(true)}>
              <PlusIcon />
              New task
            </Button>
          </EmptyContent>
        </Empty>
      ) : view === "board" ? (
        <Board orgId={org.id} board={board!} groupBy={groupBy} />
      ) : (
        <>
          <TaskList
            orgId={org.id}
            tasks={tasks!}
            sort={sort}
            descending={descending}
            onSort={(key) => {
              const next = new URLSearchParams(params);
              // Same column again flips the direction; a different one starts
              // ascending, which is what every table anyone has used does.
              next.set("dir", sort === key && !descending ? "desc" : "asc");
              next.set("sort", key);
              setParams(next, { replace: true });
            }}
          />
          {/* Said out loud, always. A list that silently stops at a hundred
              is a list you make decisions from without knowing it. */}
          <div className="flex items-center gap-3">
            <span className="font-mono text-xs text-muted-foreground">
              {tasks!.length} of {listTotal}
            </span>
            {tasks!.length < listTotal && (
              <Button variant="outline" size="sm" onClick={() => setListLimit((n) => n + PAGE)}>
                Show more
              </Button>
            )}
          </div>
        </>
      )}

      <NewTaskDialog
        open={creating}
        onOpenChange={setCreating}
        orgId={org.id}
        projects={projects}
        defaultProject={projectFilter && projectFilter !== NO_PROJECT ? projectFilter : ""}
        onCreated={load}
      />
    </>
  );
}

function Board({
  orgId,
  board,
  groupBy,
}: {
  orgId: string;
  board: BoardData;
  groupBy: GroupBy;
}) {
  // Status and priority are fixed, small enums — columns are driven by them
  // rather than by what came back, so an empty column stays on screen (a
  // board whose columns appear and disappear as work moves is one you can't
  // scan). Action-required has no such enum: it's whoever, in this
  // organisation, currently has something waiting on them, plus a "Nobody"
  // catch-all — a person with zero flagged tasks simply never gets a
  // column, and that's the entire membership, not a small fixed set worth
  // hardcoding. So those columns come straight from what the server found.
  let columns: { key: string; heading: React.ReactNode; items: Task[]; total: number }[];
  if (groupBy === "action_required") {
    // Nobody last: the point of this arrangement is "who's being waited on,
    // for what", and the catch-all for tasks asking nothing of anyone is
    // the least useful column to see first. Named columns sort by the
    // person's display name — the identical convention people and projects
    // sort by elsewhere in this product — read off the column's own first
    // task, since every column has at least one by construction.
    columns = [...board.columns]
      .sort((a, b) => {
        if (a.key === "none") return 1;
        if (b.key === "none") return -1;
        return personName(a.tasks[0]?.action_required).localeCompare(
          personName(b.tasks[0]?.action_required),
        );
      })
      .map((c) => ({
        key: c.key,
        heading:
          c.key === "none" ? (
            <span className="text-sm font-medium text-muted-foreground">Nobody</span>
          ) : (
            <span className="flex items-center gap-1.5 text-sm font-medium">
              {/* The same accent dot TaskMeta's own action-required badge
                  uses — this is that badge's own information, promoted to
                  a column heading, so it should read as the same thing. */}
              <span className="size-1.5 rounded-full bg-primary" />
              {personName(c.tasks[0]?.action_required)}
            </span>
          ),
        items: c.tasks,
        total: c.total,
      }));
  } else {
    const byKey = new Map(board.columns.map((c) => [c.key, c]));
    const keys: string[] = groupBy === "status" ? TASK_STATUSES : TASK_PRIORITIES;
    columns = keys.map((key) => ({
      key,
      heading:
        groupBy === "status" ? (
          <StatusBadge status={key as TaskStatus} />
        ) : (
          <span className="flex items-center gap-1.5 text-sm font-medium">
            <PriorityGlyph priority={key as TaskPriority} />
            {PRIORITY_LABEL[key as TaskPriority]}
          </span>
        ),
      items: byKey.get(key)?.tasks ?? [],
      total: byKey.get(key)?.total ?? 0,
    }));
  }

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
      {columns.map((column) => (
        <div key={column.key} className="flex flex-col gap-2 rounded-xl bg-muted/40 p-2">
          <div className="flex items-center justify-between px-1 py-1">
            {column.heading}
            {/* The real total, not what fits. "50" beside a column holding
                812 is the board lying about how much work there is. */}
            <span className="font-mono text-xs text-muted-foreground">
              {column.items.length < column.total
                ? `${column.items.length} of ${column.total}`
                : column.total}
            </span>
          </div>
          {column.items.map((task) => (
            <Link
              key={task.id}
              to={`/orgs/${orgId}/tasks/${task.id}`}
              className="group space-y-2 rounded-lg border bg-card p-3 transition-colors hover:bg-accent/50"
            >
              <div className="flex items-start gap-2">
                {/* The glyph is redundant in the priority arrangement — but
                    dropping it would make cards jump between views, and the
                    column heading is off-screen once you've scrolled. */}
                <PriorityGlyph priority={task.priority} className="mt-0.5" />
                <span className="min-w-0 flex-1 text-sm font-medium">{task.title}</span>
                <HiddenMark task={task} />
                <ClosedBadge isOpen={task.is_open} />
              </div>
              {/* Redundant only when status itself is the column; grouped by
                  priority or by action-required, it's the one place left
                  that says where the task actually stands. */}
              {groupBy !== "status" && <StatusBadge status={task.status} />}
              <TaskMeta task={task} hideActionRequired={groupBy === "action_required"} />
            </Link>
          ))}
          {column.items.length === 0 && (
            <p className="px-1 py-2 text-xs text-muted-foreground">Nothing here.</p>
          )}
          {column.items.length < column.total && (
            <Link
              to={`/orgs/${orgId}/tasks?view=list`}
              className="px-1 py-2 text-xs text-muted-foreground underline underline-offset-2"
            >
              {column.total - column.items.length} more — see the list
            </Link>
          )}
        </div>
      ))}
    </div>
  );
}

/** The columns, in order. `sort` is the server-side key; a column without one
 *  can\'t be sorted (nothing here needs that yet, but tags would). */
const COLUMNS = [
  { key: "title", label: "Task", sort: "title" },
  { key: "project", label: "Project", sort: "project" },
  { key: "status", label: "Status", sort: "status" },
  { key: "priority", label: "Priority", sort: "priority" },
  { key: "owner", label: "Owner", sort: "owner" },
  { key: "action_required", label: "Action required", sort: "action_required" },
  { key: "created_at", label: "Created", sort: "created_at" },
  { key: "updated_at", label: "Updated", sort: "updated_at" },
] as const;

function TaskList({
  orgId,
  tasks,
  sort,
  descending,
  onSort,
}: {
  orgId: string;
  tasks: Task[];
  sort: string | null;
  descending: boolean;
  onSort: (key: string) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            {COLUMNS.map((column) => (
              <TableHead key={column.key}>
                {/* Sorting is the server's job — the page is a page, so
                    ordering the rows in the browser would only order the
                    hundred you happen to be holding. */}
                <button
                  type="button"
                  className="flex items-center gap-1 hover:text-foreground"
                  aria-label={`Sort by ${column.label}`}
                  onClick={() => onSort(column.sort)}
                >
                  {column.label}
                  {sort === column.sort &&
                    (descending ? (
                      <ArrowDownIcon className="size-3" />
                    ) : (
                      <ArrowUpIcon className="size-3" />
                    ))}
                </button>
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {tasks.map((task) => (
            <TableRow key={task.id}>
              <TableCell className="max-w-72">
                <Link
                  to={`/orgs/${orgId}/tasks/${task.id}`}
                  className="flex items-center gap-2 font-medium hover:underline"
                >
                  <span className="truncate">{task.title}</span>
                  <HiddenMark task={task} />
                  <ClosedBadge isOpen={task.is_open} />
                </Link>
                {task.tags.length > 0 && (
                  <span className="mt-1 flex flex-wrap gap-1">
                    {task.tags.map((tag) => (
                      <TagChip key={tag.id} tag={tag} className="text-xs" />
                    ))}
                  </span>
                )}
              </TableCell>
              <TableCell className="max-w-40 truncate text-muted-foreground">
                {task.project_name ?? <span className="italic">No project</span>}
              </TableCell>
              <TableCell>
                <StatusBadge status={task.status} />
              </TableCell>
              <TableCell>
                <PriorityGlyph priority={task.priority} withLabel />
              </TableCell>
              <TableCell className="max-w-40 truncate">{personName(task.owner)}</TableCell>
              <TableCell className="max-w-40 truncate">
                {task.action_required ? (
                  personName(task.action_required)
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </TableCell>
              {/* Dates in the mono voice, like every other machine value, so
                  the columns line up rather than ragging. */}
              <TableCell className="font-mono text-xs text-muted-foreground">
                {timestamp(task.created_at)}
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">
                {ago(task.updated_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** Only the owner ever sees a hidden task, so this is never a warning about
 *  somebody else's work — it's "remember, nobody else can see this one". */
function HiddenMark({ task }: { task: Task }) {
  if (!task.is_hidden) return null;
  return (
    <EyeOffIcon
      className="size-3.5 shrink-0 text-muted-foreground"
      aria-label="Hidden from everyone else"
    />
  );
}

function TaskMeta({
  task,
  hideActionRequired,
}: {
  task: Task;
  /** The action-required board: the column already says who, so repeating
   *  it on every card is the exact redundancy status and priority avoid on
   *  their own boards. */
  hideActionRequired?: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      {task.tags.map((tag) => (
        <TagChip key={tag.id} tag={tag} className="text-xs" />
      ))}
      {task.project_name && <span className="truncate">{task.project_name}</span>}
      {!task.project_id && <span className="italic">No project</span>}
      {task.due_on && <span className="font-mono">{task.due_on}</span>}
      {/* The one thing on a card that's asking something of a person, so it
          gets the accent rather than blending into the metadata line. */}
      {task.action_required && !hideActionRequired && (
        <Badge variant="outline" className="gap-1.5 text-primary">
          <span className="size-1.5 rounded-full bg-primary" />
          {personName(task.action_required)}
        </Badge>
      )}
    </div>
  );
}

