import {
  CheckCircle2Icon,
  CircleDotIcon,
  EyeIcon,
  EyeOffIcon,
  HistoryIcon,
  LockIcon,
  PinIcon,
  PlusIcon,
  RepeatIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router-dom";

import { ApiError, api } from "@/api";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useRealtime } from "@/hooks/use-realtime";
import type { Shell } from "@/App";
import { AccessPanel } from "@/components/access-panel";
import { ChecklistsPanel } from "@/components/checklist-panel";
import { SheetsPanel } from "@/components/sheet-panel";
import { CommentThread } from "@/components/comment-thread";
import { DependenciesPanel } from "@/components/dependencies-panel";
import { EntityPicker, type PickerItem } from "@/components/entity-picker";
import { PageHeader } from "@/components/page-header";
import { PriorityGlyph } from "@/components/priority";
import { RichText, RichTextEditor } from "@/components/rich-text";
import { PrivateNote } from "@/components/private-note";
import { ReminderPanel } from "@/components/reminder-panel";
import { ClosedBadge, StatusBadge } from "@/components/status-badge";
import { TagStrip } from "@/components/tag-picker";
import { FilesPanel } from "@/components/files-panel";
import { TimePanel } from "@/components/time-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { useToastManager } from "@/components/ui/toast";
import { timestamp } from "@/lib/format";
import {
  LEVEL_LABEL,
  PLANNER_BUCKETS,
  PLANNER_BUCKET_LABEL,
  PRIORITY_LABEL,
  STATUS_DOT,
  STATUS_LABEL,
  TASK_PRIORITIES,
  TASK_STATUSES,
  canEdit,
  personName,
  type Member,
  type PlannerBucket,
  type Project,
  type Task,
  type TaskAccess,
  type TaskEvent,
  type Team,
  type TaskPriority,
  type TaskStatus,
} from "@/lib/types";

/**
 * The three panels that stay collapsed until they hold something.
 *
 * Labels are what the button says after the plus, so they read as the thing
 * being added ("+ Checklist") rather than as the card's own plural heading —
 * except "Depends on", which has no singular worth inventing and is what the
 * card is actually called. Order matches the order they render in, so the
 * card appears directly above the button that revealed it.
 */
const EXTRAS = [
  { key: "checklists", label: "Checklist" },
  { key: "sheets", label: "Sheet" },
  { key: "dependencies", label: "Depends on" },
  { key: "files", label: "Files" },
  // Not in the row with the others: its card is at the very bottom of the
  // column, and a button up here would reveal something below the fold —
  // which reads as a button that did nothing. It gets its own button, in
  // the place its card appears. See `noteButton` below.
  { key: "note", label: "Private note" },
] as const;

type ExtraKey = (typeof EXTRAS)[number]["key"];

export default function TaskDetail() {
  const { orgId, taskId } = useParams<{ orgId: string; taskId: string }>();
  const { organisations, me, timer, refreshTimer } = useOutletContext<Shell>();
  const navigate = useNavigate();
  const toast = useToastManager();
  const org = organisations.find((o) => o.id === orgId) ?? null;
  // Mirrors the grid's own `2xl` breakpoint — see the comment above the
  // grid for why this is decided in JS rather than with a second, hidden
  // copy of <CommentThread> toggled by CSS. Called unconditionally, above
  // every early `return` below, same as every other hook in this component.
  const isWide = useMediaQuery("(min-width: 1536px)");

  const [task, setTask] = useState<Task | null>(null);
  const [accessInfo, setAccessInfo] = useState<TaskAccess | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [gone, setGone] = useState(false);
  // Comments can carry files, so posting one has to reach the Files panel.
  const [filesKey, setFilesKey] = useState(0);
  // Checklists and Sheets fetch separately, same reasoning as the Files
  // panel: a realtime event needs its own nudge to reach a panel that isn't
  // `load()`.
  const [checklistsKey, setChecklistsKey] = useState(0);
  const [sheetsKey, setSheetsKey] = useState(0);
  const [dependenciesKey, setDependenciesKey] = useState(0);
  // Checklists, Sheets and Depends on are rare on any given task, and three
  // empty cards is most of a screen spent saying "nothing here". Each stays
  // collapsed behind a "+ Checklist" button — the same affordance "+ Tag"
  // already is — until its own panel reports something in it, or somebody
  // presses the button. "loading" until the panel has answered, so the
  // button never flashes on a task that turns out to have one.
  const [extras, setExtras] = useState<Record<ExtraKey, "loading" | "empty" | "open">>({
    checklists: "loading",
    sheets: "loading",
    dependencies: "loading",
    files: "loading",
    note: "loading",
  });
  const openExtra = useCallback(
    (key: ExtraKey) => setExtras((prev) => ({ ...prev, [key]: "open" })),
    [],
  );
  // A panel opens the moment it has anything to show and never closes itself
  // again: deleting the last checklist shouldn't yank the card out from
  // under the person who just deleted it.
  const onExtraLoaded = useCallback(
    (key: ExtraKey, hasContent: boolean) =>
      setExtras((prev) => ({
        ...prev,
        [key]: prev[key] === "open" || hasContent ? "open" : "empty",
      })),
    [],
  );
  // Type-the-title-to-confirm — the same bar as deleting an organisation or a
  // project, and for the same reason: a bare "Are you sure?" is exactly the
  // dialog a habitual double-click sails through.
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  const load = useCallback(async () => {
    if (!orgId || !taskId) return;
    try {
      const t = await api<Task>(`/organisations/${orgId}/tasks/${taskId}`);
      setTask(t);
      const [acc, evs, ms, ps, tms] = await Promise.all([
        api<TaskAccess>(`/organisations/${orgId}/tasks/${taskId}/access`),
        api<TaskEvent[]>(`/organisations/${orgId}/tasks/${taskId}/events`),
        api<Member[]>(`/organisations/${orgId}/members`),
        api<Project[]>(`/organisations/${orgId}/projects`),
        api<Team[]>(`/organisations/${orgId}/teams`),
      ]);
      setAccessInfo(acc);
      setEvents(evs);
      setMembers(ms);
      setProjects(ps);
      setTeams(tms);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setGone(true);
    }
  }, [orgId, taskId]);

  useEffect(() => {
    void load();
  }, [load]);

  const onCommentsChanged = useCallback(() => setFilesKey((k) => k + 1), []);

  // Live updates for the task itself — a status, a file, a due date, a timer
  // somebody started. The event carries nothing but the id, so this refetches
  // and gets the same answer the screen would have got on a reload; if access
  // went away in between, that refetch 404s and the screen says so.
  //
  // Deliberately **not** filtered by `change`: a screen that only refreshes
  // for the kinds it recognises stops refreshing the day somebody adds a
  // sixth one, and the failure is invisible.
  useRealtime(
    useCallback(
      (event) => {
        if (event.type === "task" && event.task_id === taskId) {
          void load();
          // The Files, Checklists, Sheets and Dependencies panels fetch
          // separately, so each needs its own nudge.
          setFilesKey((k) => k + 1);
          setChecklistsKey((k) => k + 1);
          setSheetsKey((k) => k + 1);
          setDependenciesKey((k) => k + 1);
        }
      },
      [taskId, load],
    ),
    useMemo(
      () => (taskId ? { kind: "task" as const, id: taskId } : undefined),
      [taskId],
    ),
  );

  if (!org) return null;

  if (gone) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <LockIcon />
          </EmptyMedia>
          <EmptyTitle>You don&rsquo;t have access to this task</EmptyTitle>
          <EmptyDescription>
            It may have been deleted, or never shared with you.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button render={<Link to={`/orgs/${org.id}/tasks`} />} nativeButton={false}>
            Back to tasks
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  if (!task || !accessInfo) {
    return (
      <div className="flex flex-1 items-center justify-center py-12">
        <Spinner />
        <span className="sr-only">Loading</span>
      </div>
    );
  }

  const editable = canEdit(task.access);
  // Only the ones that have answered and turned out to be empty: "loading"
  // offers no button yet, and "open" no longer needs one.
  //
  // The private note is in this row alongside the rest, and it is the one
  // entry **not** gated on `editable`: a note is yours, not task content,
  // and `services/notes.py`'s rule is that seeing the task is enough to
  // keep one. Gating it here would quietly take the feature away from
  // exactly the read-only viewer most likely to be keeping notes on
  // somebody else's work — so a viewer with no write access gets a row
  // holding that one button, which is why the row itself is no longer
  // gated on `editable` either.
  const collapsedExtras = EXTRAS.filter(
    ({ key }) => extras[key] === "empty" && (editable || key === "note"),
  );
  const extraButton = (key: ExtraKey, label: string) => (
    <Button
      key={key}
      size="xs"
      variant="ghost"
      className="text-muted-foreground"
      onClick={() => openExtra(key)}
    >
      <PlusIcon />
      {label}
    </Button>
  );

  const act = async (fn: () => Promise<unknown>, success: string) => {
    try {
      await fn();
      await load();
      toast.add({ title: success });
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "That didn't work", description: detail });
    }
  };

  // Its own endpoint, not `patch()` — the planner is personal to the caller
  // (`read` is enough, the identical bar `services/pins.py` sets for the
  // same reason), not a property of the task the way status or due date
  // are. `null` removes the entry rather than PUTting an empty bucket —
  // "unplanned" is the absence of a row, not a sixth bucket.
  const setPlanner = (bucket: PlannerBucket | null) =>
    act(
      () =>
        bucket
          ? api(`/organisations/${org.id}/planner/${task.id}`, {
              method: "PUT",
              body: JSON.stringify({ bucket }),
            })
          : api(`/organisations/${org.id}/planner/${task.id}`, { method: "DELETE" }),
      bucket ? `Added to ${PLANNER_BUCKET_LABEL[bucket]}` : "Removed from your planner",
    );

  const patch = (body: Record<string, unknown>, success: string) =>
    act(
      () =>
        api(`/organisations/${org.id}/tasks/${task.id}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        }),
      success,
    );

  // The email is the hint line, and it's searched as well as shown — two
  // people called Jan is the ordinary case, not the edge one.
  const people: PickerItem[] = members
    .filter((m) => m.status === "active" && m.user_id)
    .map((m) => ({
      value: m.user_id!,
      label: m.display_name || m.email || "Unknown",
      hint: m.display_name ? (m.email ?? undefined) : undefined,
    }));

  // Held in a variable for the same reason `commentThread` is: it now
  // renders in whichever column the thread ended up in, and that is decided
  // in JS rather than by a CSS breakpoint. History reads as the tail of the
  // conversation — who changed what, next to who said what — so the two
  // stay together at every width instead of History being stranded under
  // Files once Comments moves to its own column.
  const history = (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <HistoryIcon className="size-4" />
          History
        </CardTitle>
      </CardHeader>
      <CardContent>
        {/* Append-only, and the only record of work on a task. Rendered
            oldest-first so it reads as a story rather than a feed. */}
        <ol className="space-y-3">
          {events.map((event) => (
            <li key={event.id} className="flex gap-3 text-sm">
              <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-border" />
              <span className="min-w-0 flex-1">
                <span>{describeEvent(event)}</span>{" "}
                <span className="font-mono text-xs text-muted-foreground">
                  {timestamp(event.created_at)}
                </span>
              </span>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );

  const commentThread = (
    <CommentThread
      orgId={org.id}
      anchor="tasks"
      anchorId={task.id}
      onChanged={onCommentsChanged}
      // Write access to switch it, same bar as the sidebar's own Action
      // required field — a read-only viewer can still comment, just not
      // reassign the task while doing it.
      actionRequiredCandidates={editable ? people : undefined}
    />
  );

  // Only projects you can edit. Filing work into someone's project changes
  // what they see; the API enforces it, this avoids offering a 403.
  const projectItems: PickerItem[] = projects
    .filter((p) => p.access !== "read" && !p.archived)
    .map((p) => ({ value: p.id, label: p.name, hint: p.project_group_name ?? undefined }));

  // Where it is now always appears, even if you couldn't file it there
  // yourself — otherwise the control reads as "no project" and moving it
  // somewhere else looks like the only option.
  if (task.project_id && !projectItems.some((i) => i.value === task.project_id)) {
    projectItems.unshift({ value: task.project_id, label: task.project_name ?? "Its project" });
  }

  return (
    <>
      <PageHeader
        crumbs={[
          { label: org.name, to: `/orgs/${org.id}` },
          { label: "Tasks", to: `/orgs/${org.id}/tasks` },
          // Goes to the task list filtered to this project, not the
          // project's own detail page — "Tasks" then "ProjectName" reads as
          // a drill-down (all tasks -> this project's tasks -> this task),
          // and it's the screen you actually came from when you opened a
          // task off a board or list. Linked only when the caller can
          // actually see the filtered result. A task-level grant can reach
          // further than the project's own — the same gap
          // effective_task_level documents — so seeing the project's name
          // here doesn't mean seeing its tasks. `projects` is already
          // scoped to what this caller can see (the same fetch behind the
          // move-task picker), so membership in it is the real answer rather
          // than a guess from a structural field like `inherits_from_project`.
          ...(task.project_name
            ? [
                {
                  label: task.project_name,
                  to: projects.some((p) => p.id === task.project_id)
                    ? `/orgs/${org.id}/tasks?project=${task.project_id}`
                    : undefined,
                },
              ]
            : []),
          { label: task.title },
        ]}
        title={task.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge status={task.status} />
            <PriorityGlyph priority={task.priority} withLabel />
            <ClosedBadge isOpen={task.is_open} />
            {/* Anyone reading this is the owner — nobody else can load the
                page at all — so it's a statement of fact, not a warning. */}
            {task.is_hidden && (
              <Badge variant="outline" className="gap-1.5">
                <EyeOffIcon className="size-3.5" />
                Hidden
              </Badge>
            )}
            <Badge variant="outline">{LEVEL_LABEL[task.access]}</Badge>
            {!task.project_id && (
              <span className="text-muted-foreground italic">No project</span>
            )}
          </span>
        }
        actions={
          <span className="flex items-center gap-2">
            {/* Yours to set regardless of edit access — see services/pins.py.
                A pin is a personal bookmark, not a change to the task, so
                read is enough and there's nothing to disable here. */}
            <Button
              variant="ghost"
              aria-label={task.is_pinned ? "Unpin task" : "Pin task"}
              onClick={() =>
                act(
                  () =>
                    api(`/organisations/${org.id}/tasks/${task.id}/pin`, {
                      method: task.is_pinned ? "DELETE" : "POST",
                    }),
                  task.is_pinned ? "Unpinned" : "Pinned to your dashboard",
                )
              }
            >
              <PinIcon className={task.is_pinned ? "fill-current" : undefined} />
              {task.is_pinned ? "Pinned" : "Pin"}
            </Button>
            {/* Only the owner (or an org admin) closes — resolved server-side
                and sent as `can_close`, so the button isn't there for anyone
                else rather than being there and 403-ing. */}
            {task.can_close && (
              <Button
                variant={task.is_open ? "default" : "outline"}
                onClick={() =>
                  act(
                    () =>
                      api(`/organisations/${org.id}/tasks/${task.id}/closed`, {
                        method: "POST",
                        body: JSON.stringify({ closed: task.is_open }),
                      }),
                    task.is_open ? "Closed" : "Reopened",
                  )
                }
              >
                {task.is_open ? <CheckCircle2Icon /> : <CircleDotIcon />}
                {task.is_open ? "Close task" : "Reopen"}
              </Button>
            )}
          </span>
        }
      />

      <TagStrip
        orgId={org.id}
        taskId={task.id}
        tags={task.tags}
        editable={editable}
        onChanged={load}
      />

      {/* Comments gets its own column from `2xl` up, between this main
          column and the sidebar. That can't be done with `col-start` alone:
          an early version split this column into two grid children (Details
          through Files, then History+note) so Comments could sit between
          them at `lg` and move out at `2xl`, but that puts three siblings in
          row 1 (Details-through-Files, Comments-or-sidebar) whose auto row
          height is the *tallest* of them — the sidebar, being by far the
          longest card — which stretched the shorter Details-through-Files
          cell to match and left a dead gap between Files and History before
          the next row even started. Two grid rows sharing a track with a
          much taller sidebar is the trap; the fix is to not have two rows.
          `isWide` (`useMediaQuery`, mirroring the grid's own `2xl` in JS —
          both must stay at 1536px) decides, once, whether `<CommentThread>`
          mounts inline inside this single column-1 div (below `2xl`, its
          original position between Files and History) or as its own
          sibling grid item (at `2xl`, between this column and the sidebar).
          It only ever mounts once — never both at once behind a `hidden`
          class — because it holds its own thread state and a realtime
          subscription; mounting two copies live at once would double both. */}
      <div className="grid gap-4 lg:grid-cols-[1fr_22rem] 2xl:grid-cols-[1fr_28rem_22rem]">
        <div className="space-y-4 lg:col-start-1">
          <Card>
            <CardHeader>
              <CardTitle>Details</CardTitle>
            </CardHeader>
            <CardContent>
              <Details
                task={task}
                orgId={org.id}
                editable={editable}
                onSaved={load}
                onImageAdded={onCommentsChanged}
              />
            </CardContent>
          </Card>

          <ChecklistsPanel
            orgId={org.id}
            taskId={task.id}
            canEdit={editable}
            refreshKey={checklistsKey}
            open={extras.checklists === "open"}
            onLoaded={(has) => onExtraLoaded("checklists", has)}
          />

          <SheetsPanel
            orgId={org.id}
            taskId={task.id}
            canEdit={editable}
            refreshKey={sheetsKey}
            open={extras.sheets === "open"}
            onLoaded={(has) => onExtraLoaded("sheets", has)}
          />

          <DependenciesPanel
            orgId={org.id}
            taskId={task.id}
            canEdit={editable}
            refreshKey={dependenciesKey}
            open={extras.dependencies === "open"}
            onLoaded={(has) => onExtraLoaded("dependencies", has)}
          />

          {/* What the panels around it collapse to while they're empty. It
              sits between them on purpose: the three above reveal upwards
              into the space they already occupy, Files reveals downwards
              into its own — either way the card lands where you were
              already looking. The row disappears once there is nothing
              left to add. */}
          {collapsedExtras.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              {collapsedExtras.map(({ key, label }) => extraButton(key, label))}
            </div>
          )}

          {/* Above the thread: the files are part of what the task *is*, and
              a panel below a conversation that grows all day is a panel
              nobody finds twice. */}
          <FilesPanel
            orgId={org.id}
            basePath={`/organisations/${org.id}/tasks/${task.id}`}
            canEdit={editable}
            refreshKey={filesKey}
            emptyHint="Files posted in comments show up here too."
            open={extras.files === "open"}
            onLoaded={(has) => onExtraLoaded("files", has)}
          />

          {/* Directly under Files, which is where its own button in the row
              above reveals it — the same "the card lands where you were
              already looking" rule every other panel in this column
              follows. It used to sit last on the page, after History, on
              the reasoning that everything above it is shared with
              somebody by construction and this one card never is; that
              ordering lost out to keeping the button and the card it
              opens within sight of each other. It's still the last card
              in this column at `2xl`, where Comments and History move
              out. See components/private-note.tsx. */}
          <PrivateNote
            orgId={org.id}
            taskId={task.id}
            open={extras.note === "open"}
            onLoaded={(has) => onExtraLoaded("note", has)}
          />

          {!isWide && (
            <>
              {commentThread}
              {history}
            </>
          )}
        </div>

        {/* Only rendered once `isWide`, at which point the grid is already
            in its `2xl`, three-column configuration — so this needs no
            `lg:`/`2xl:` prefixing of its own, unlike the sidebar below,
            which must keep responding to the CSS breakpoint directly since
            it renders at every width. */}
        {isWide && (
          <div className="space-y-4 col-start-2 row-start-1">
            {commentThread}
            {history}
          </div>
        )}

        <div className="space-y-4 lg:col-start-2 lg:row-start-1 2xl:col-start-3">
          <Card>
            <CardHeader>
              <CardTitle>Status</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* The four switches somebody actually comes to this panel for,
                  in the order they're asked about — where it stands, who it's
                  waiting on, how urgent, and by when. Owner and Project are
                  assignment, not status, and live in their own card below. */}
              <Field
                label="Status"
                help="Status and open/closed are separate — a task can be closed at any status."
              >
                <EntityPicker
                  ariaLabel="Status"
                  items={TASK_STATUSES.map((s) => ({
                    value: s,
                    label: STATUS_LABEL[s],
                    icon: <span className={`size-2 rounded-full ${STATUS_DOT[s]}`} />,
                  }))}
                  value={task.status}
                  disabled={!editable}
                  searchPlaceholder="Filter…"
                  onChange={(v) => v && patch({ status: v as TaskStatus }, "Status updated")}
                />
              </Field>
              <Field
                label="Action required"
                help="At most one person, notified the moment you set it. Clearing it is not a close."
              >
                <EntityPicker
                  ariaLabel="Action required"
                  items={people}
                  value={task.action_required?.id ?? null}
                  disabled={!editable}
                  placeholder="Nobody"
                  emptyLabel="Nobody"
                  searchPlaceholder="Find a person…"
                  onChange={(v) =>
                    patch(
                      { action_required_user_id: v },
                      v ? "They've been notified" : "Cleared",
                    )
                  }
                />
              </Field>
              <Field
                label="Priority"
                help="How urgent, independent of status. The board can group by it."
              >
                <EntityPicker
                  ariaLabel="Priority"
                  items={TASK_PRIORITIES.map((p) => ({
                    value: p,
                    label: PRIORITY_LABEL[p],
                    icon: <PriorityGlyph priority={p} />,
                  }))}
                  value={task.priority}
                  disabled={!editable}
                  searchPlaceholder="Filter…"
                  onChange={(v) =>
                    v && patch({ priority: v as TaskPriority }, "Priority updated")
                  }
                />
              </Field>
              <div className="space-y-2">
                <Label htmlFor="due">Due</Label>
                <Input
                  id="due"
                  type="date"
                  disabled={!editable}
                  value={task.due_on ?? ""}
                  onChange={(e) => patch({ due_on: e.target.value || null }, "Due date updated")}
                />
              </div>
              <Field
                label="Planner"
                help="Yours alone — which bucket it sits in on your own Planner board."
              >
                <EntityPicker
                  ariaLabel="Planner"
                  items={PLANNER_BUCKETS.map((b) => ({
                    value: b,
                    label: PLANNER_BUCKET_LABEL[b],
                  }))}
                  value={task.planner_bucket}
                  placeholder="Not planned"
                  emptyLabel="Not planned"
                  searchPlaceholder="Filter…"
                  onChange={(v) => setPlanner(v as PlannerBucket | null)}
                />
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-2">
                  <Label htmlFor="estimated-start">Est. start</Label>
                  <Input
                    id="estimated-start"
                    type="date"
                    disabled={!editable}
                    value={task.estimated_start_on ?? ""}
                    onChange={(e) =>
                      patch(
                        { estimated_start_on: e.target.value || null },
                        "Estimated start updated",
                      )
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="estimated-hours">Est. hours</Label>
                  <Input
                    id="estimated-hours"
                    type="number"
                    min={0}
                    max={9999.9}
                    step={0.1}
                    disabled={!editable}
                    value={task.estimated_hours ?? ""}
                    onChange={(e) =>
                      patch(
                        { estimated_hours: e.target.value === "" ? null : Number(e.target.value) },
                        "Estimated hours updated",
                      )
                    }
                  />
                </div>
              </div>
              <RecurrenceControl orgId={org.id} task={task} editable={editable} onChanged={load} />
            </CardContent>
          </Card>

          {/* Straight after Status and ahead of Assignment: starting the
              clock is something you do about the state of the work, and it
              wants to be the first thing under it rather than four cards
              down past who owns it. */}
          <TimePanel
            orgId={org.id}
            taskId={task.id}
            meId={me?.id}
            timer={timer}
            // Reload the task too, not just the header clock: logging or
            // correcting time writes a `task_events` row, and the History card
            // is on the same screen. Refreshing one and not the other leaves
            // the trail looking like it didn't record anything.
            onTimerChanged={async () => {
              await refreshTimer();
              await load();
            }}
          />

          <Card>
            <CardHeader>
              <CardTitle>Assignment</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Field
                label="Owner"
                help="Responsible for it, and the only person who can close it."
              >
                <EntityPicker
                  ariaLabel="Owner"
                  items={people}
                  value={task.owner?.id ?? null}
                  disabled={!accessInfo.can_manage}
                  searchPlaceholder="Find a person…"
                  onChange={(v) => v && patch({ owner_user_id: v }, "Owner changed")}
                />
              </Field>
              <Field
                label="Project"
                help="Moving it hands its visibility to the new project — everyone who can see that project can see this."
              >
                <EntityPicker
                  ariaLabel="Project"
                  items={projectItems}
                  value={task.project_id}
                  disabled={!editable}
                  placeholder="No project"
                  emptyLabel="No project"
                  searchPlaceholder="Find a project…"
                  onChange={(v) =>
                    patch({ project_id: v }, v ? "Moved" : "Taken out of its project")
                  }
                />
              </Field>
            </CardContent>
          </Card>

          <ReminderPanel orgId={org.id} taskId={task.id} />

          <TaskAccessCard
            task={task}
            orgId={org.id}
            access={accessInfo}
            canOpenProject={projects.some((p) => p.id === task.project_id)}
            onToggleHidden={
              task.can_hide
                ? () =>
                    act(
                      () =>
                        api(`/organisations/${org.id}/tasks/${task.id}/hidden`, {
                          method: "POST",
                          body: JSON.stringify({ hidden: !task.is_hidden }),
                        }),
                      task.is_hidden ? "Visible again" : "Hidden",
                    )
                : undefined
            }
          />

          {/* Share this one task without sharing its whole project — the
              same component ProjectDetail's own access card already uses,
              pointed at the task's identical POST/PATCH/DELETE .../access
              shape. Sharing stays set up while hidden (see TaskAccessCard's
              own copy above), so this isn't gated on task.is_hidden. */}
          <AccessPanel
            basePath={`/organisations/${org.id}/tasks/${task.id}`}
            access={accessInfo}
            members={members}
            teams={teams}
            onChanged={load}
          />

          {accessInfo.can_manage && (
            <Card>
              <CardContent className="pt-6">
                <Button variant="destructive" onClick={() => setConfirmingDelete(true)}>
                  <Trash2Icon />
                  Delete task
                </Button>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <Dialog
        open={confirmingDelete}
        onOpenChange={(open) => {
          setConfirmingDelete(open);
          if (!open) setConfirmText("");
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {task.title}?</DialogTitle>
            <DialogDescription>
              This removes it, its comments, files and history. It cannot be undone. Type the
              title to confirm.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={confirmText}
            placeholder={task.title}
            onChange={(e) => setConfirmText(e.target.value)}
          />
          <DialogFooter>
            <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
            <Button
              variant="destructive"
              disabled={confirmText !== task.title}
              onClick={() =>
                act(async () => {
                  await api(`/organisations/${org.id}/tasks/${task.id}`, {
                    method: "DELETE",
                  });
                  setConfirmingDelete(false);
                  navigate(`/orgs/${org.id}/tasks`);
                }, "Task deleted")
              }
            >
              Delete permanently
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function Details({
  task,
  orgId,
  editable,
  onSaved,
  onImageAdded,
}: {
  task: Task;
  orgId: string;
  editable: boolean;
  onSaved: () => Promise<void>;
  /** A picture pasted into the description is a task file too. */
  onImageAdded?: () => void;
}) {
  const toast = useToastManager();
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description ?? "");
  // Write/Preview, the same pair GitHub's own markdown fields use — a
  // mermaid diagram only renders in RichText's read-only path, so without
  // this the person actually drawing one would never see it themselves.
  const [mode, setMode] = useState<"write" | "preview">("write");

  if (!editable) {
    return (
      <div className="space-y-2 text-sm">
        {task.description ? (
          <RichText html={task.description} />
        ) : (
          <p className="text-muted-foreground">No description.</p>
        )}
        <p className="text-xs text-muted-foreground">You have view-only access to this task.</p>
      </div>
    );
  }

  const dirty = title !== task.title || description !== (task.description ?? "");

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="task-title">Title</Label>
        <Input id="task-title" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label>Description</Label>
          <div className="flex items-center gap-1 text-xs">
            <Button
              type="button"
              size="sm"
              variant={mode === "write" ? "secondary" : "ghost"}
              onClick={() => setMode("write")}
            >
              Write
            </Button>
            <Button
              type="button"
              size="sm"
              variant={mode === "preview" ? "secondary" : "ghost"}
              onClick={() => setMode("preview")}
            >
              Preview
            </Button>
          </div>
        </div>
        {mode === "write" ? (
          <RichTextEditor
            orgId={orgId}
            basePath={`/organisations/${orgId}/tasks/${task.id}`}
            value={description}
            onChange={setDescription}
            onImageAdded={onImageAdded}
          />
        ) : description ? (
          <div className="rounded-lg border px-3 py-2">
            <RichText html={description} />
          </div>
        ) : (
          <p className="rounded-lg border px-3 py-2 text-sm text-muted-foreground">
            Nothing to preview yet.
          </p>
        )}
      </div>
      <Button
        disabled={!dirty || !title.trim()}
        onClick={async () => {
          await api(`/organisations/${orgId}/tasks/${task.id}`, {
            method: "PATCH",
            body: JSON.stringify({ title: title.trim(), description }),
          });
          await onSaved();
          toast.add({ title: "Saved" });
        }}
      >
        Save
      </Button>
    </div>
  );
}

/**
 * Turn this task into the first occurrence of a series, or show the one
 * it's already part of. On schedule, not on close — the next occurrence
 * appears whether or not this one is done, so there's no "resume" here,
 * only "stop": once a series is generating, the only lever this control
 * offers is turning it off.
 */
function RecurrenceControl({
  orgId,
  task,
  editable,
  onChanged,
}: {
  orgId: string;
  task: Task;
  editable: boolean;
  onChanged: () => Promise<void>;
}) {
  const toast = useToastManager();
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState("1");
  const [unit, setUnit] = useState<"day" | "week" | "month">("week");
  const [busy, setBusy] = useState(false);

  const fail = (err: unknown, title: string) => {
    const detail = err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
    toast.add({ title, description: detail });
  };

  const submit = async () => {
    const n = parseInt(count, 10);
    if (!n || n < 1 || busy) return;
    setBusy(true);
    try {
      await api(`/organisations/${orgId}/tasks/${task.id}/recurrence`, {
        method: "POST",
        body: JSON.stringify({ interval_unit: unit, interval_count: n }),
      });
      setOpen(false);
      await onChanged();
      toast.add({ title: "Now repeating" });
    } catch (err) {
      fail(err, "Couldn't set that up");
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    try {
      await api(`/organisations/${orgId}/tasks/${task.id}/recurrence/stop`, { method: "POST" });
      await onChanged();
      toast.add({ title: "Stopped repeating" });
    } catch (err) {
      fail(err, "Couldn't stop that");
    }
  };

  if (task.recurrence) {
    const { interval_count, interval_unit, next_due_on, active, can_manage } = task.recurrence;
    const cadence =
      interval_count === 1 ? `every ${interval_unit}` : `every ${interval_count} ${interval_unit}s`;
    // Stopped is permanent history on this particular task, not a live
    // state — no "Stop" button to click again, and deliberately no "restart"
    // either. A new series starts from whichever task is due next, the same
    // way generation itself works: forward from here, not backward into one
    // that already happened.
    if (!active) {
      return (
        <div className="flex items-center gap-1.5 rounded-lg border p-2 text-xs text-muted-foreground">
          <RepeatIcon className="size-3.5 shrink-0" />
          Stopped repeating {cadence}
        </div>
      );
    }
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-2 text-xs">
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <RepeatIcon className="size-3.5 shrink-0" />
          Repeats {cadence} · next on {next_due_on}
        </span>
        {can_manage && (
          <Button size="sm" variant="ghost" onClick={stop}>
            Stop
          </Button>
        )}
      </div>
    );
  }

  // Needs a due date to anchor the cadence to, and write access to set one
  // up — the same bar as any other edit to the task.
  if (!editable || !task.due_on) return null;

  if (!open) {
    return (
      <Button size="sm" variant="ghost" className="w-fit justify-start" onClick={() => setOpen(true)}>
        <RepeatIcon className="size-3.5" />
        Repeat this task
      </Button>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border p-2">
      <span className="text-xs text-muted-foreground">Every</span>
      <Input
        type="number"
        min={1}
        max={52}
        className="w-16"
        value={count}
        aria-label="Interval count"
        onChange={(e) => setCount(e.target.value)}
      />
      <select
        className="h-8 rounded-lg border bg-background px-2 text-sm"
        value={unit}
        aria-label="Interval unit"
        onChange={(e) => setUnit(e.target.value as typeof unit)}
      >
        <option value="day">day(s)</option>
        <option value="week">week(s)</option>
        <option value="month">month(s)</option>
      </select>
      <Button size="sm" disabled={busy} onClick={submit}>
        Set
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
        Cancel
      </Button>
    </div>
  );
}

/** Label, control, and the sentence explaining what the choice does. The help
 *  line isn't decoration — every one of these fields changes who sees what or
 *  who is being asked for something. */
function Field({
  label,
  help,
  children,
}: {
  label: string;
  help: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      {children}
      <p className="text-xs text-muted-foreground">{help}</p>
    </div>
  );
}

function TaskAccessCard({
  task,
  orgId,
  access,
  canOpenProject,
  onToggleHidden,
}: {
  task: Task;
  orgId: string;
  access: TaskAccess;
  /** Whether *this caller* can actually open the project, not just whether
   *  the task has one. `access.inherits_from_project` is structural (does
   *  the task belong to a project at all) — a task-level grant can reach
   *  further than the project's own, so a task can be visible to someone
   *  with zero access to the project it's filed in. Linking unconditionally
   *  would be a link that predictably 404s for exactly that person. */
  canOpenProject: boolean;
  /** Absent for anyone who isn't the owner — including org admins. */
  onToggleHidden?: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Visibility</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {/* The full list of who — owner, grants, admins — is the "Who can
            see this" card below, not repeated here. This card is only the
            things that aren't a plain grant: hidden overrides everything,
            a project passes its own access down, and action-required is a
            route in of its own. */}
        {task.is_hidden ? (
          <p className="text-muted-foreground">
            <span className="font-medium text-foreground">Only you.</span> Hiding overrides
            everything else — this task is invisible to anyone it's shared with, to anyone in its
            project, and to the organisation&rsquo;s admins.
          </p>
        ) : access.inherits_from_project ? (
          <p className="text-muted-foreground">
            Anyone who can see{" "}
            {canOpenProject ? (
              <Link
                to={`/orgs/${orgId}/projects/${task.project_id}`}
                className="font-medium text-foreground underline underline-offset-2"
              >
                {access.project_name}
              </Link>
            ) : (
              <span className="font-medium text-foreground">{access.project_name}</span>
            )}{" "}
            can see this task, at the same level.
          </p>
        ) : (
          <p className="text-muted-foreground">
            This task has no project, so only the people it's shared with can see it — not
            everyone in the organisation.
          </p>
        )}

        {access.action_required && (
          <dl className={task.is_hidden ? "opacity-50" : ""}>
            <Row label="Action required" value={personName(access.action_required)} />
          </dl>
        )}

        {onToggleHidden && (
          <div className="space-y-2 border-t pt-3">
            <Button
              variant={task.is_hidden ? "default" : "outline"}
              size="sm"
              className="w-full"
              onClick={onToggleHidden}
            >
              {task.is_hidden ? <EyeIcon /> : <EyeOffIcon />}
              {task.is_hidden ? "Make it visible again" : "Hide from everyone else"}
            </Button>
            <p className="text-xs text-muted-foreground">
              {task.is_hidden
                ? "Everything above starts working again the moment you do — nothing has to be re-shared."
                : "Nobody else will be able to open or find it, admins included. Sharing stays set up and resumes when you un-hide it."}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Row({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div
      className={`flex items-center justify-between gap-3 ${muted ? "text-muted-foreground" : ""}`}
    >
      <dt className="min-w-0 truncate">{label}</dt>
      <dd className="shrink-0 text-xs">{value}</dd>
    </div>
  );
}

/** Turns one history row into a sentence. The `data` shape differs per kind,
 *  which is why this is a switch and not a template. */
function describeEvent(event: TaskEvent): string {
  const who = event.actor ? personName(event.actor) : "The system";
  const d = event.data as Record<string, string | null>;
  switch (event.kind) {
    case "created":
      return `${who} created this task`;
    case "renamed":
      return `${who} renamed it from “${d.was}”`;
    case "status_changed":
      return `${who} moved it to ${STATUS_LABEL[d.now as TaskStatus] ?? d.now}`;
    case "hidden":
      return `${who} hid it from everyone else`;
    case "unhidden":
      return `${who} made it visible again`;
    case "priority_changed":
      return `${who} set the priority to ${
        PRIORITY_LABEL[d.now as TaskPriority]?.toLowerCase() ?? d.now
      }`;
    case "closed":
      return `${who} closed it`;
    case "reopened":
      return `${who} reopened it`;
    case "owner_changed":
      return d.reason ? `Ownership moved — ${d.reason}` : `${who} handed it over`;
    case "action_required_set":
      return `${who} asked someone to act on it`;
    case "action_required_cleared":
      return `${who} cleared the action required`;
    case "moved":
      return d.now ? `${who} moved it to another project` : `${who} took it out of its project`;
    case "due_changed":
      return d.now ? `${who} set the due date to ${d.now}` : `${who} removed the due date`;
    case "access_granted":
      return `${who} shared it`;
    case "access_revoked":
      return `${who} removed someone's access`;
    case "time_logged":
      return d.minutes
        ? `${who} logged ${d.minutes}m`
        : d.reason
          ? `${who} stopped a timer — ${d.reason}`
          : `${who} logged time`;
    case "time_edited":
      return d.was_minutes
        ? `${who} corrected ${d.was_minutes}m to ${d.now_minutes}m`
        : `${who} edited a time entry`;
    case "time_deleted":
      return `${who} removed a ${d.minutes}m entry`;
    default:
      return `${who} changed something`;
  }
}
