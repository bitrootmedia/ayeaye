import {
  CheckCircle2Icon,
  CircleDotIcon,
  EyeIcon,
  EyeOffIcon,
  HistoryIcon,
  LockIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router-dom";

import { ApiError, api } from "@/api";
import type { Shell } from "@/App";
import { CommentThread } from "@/components/comment-thread";
import { EntityPicker, type PickerItem } from "@/components/entity-picker";
import { PageHeader } from "@/components/page-header";
import { PriorityGlyph } from "@/components/priority";
import { PrivateNote } from "@/components/private-note";
import { ReminderPanel } from "@/components/reminder-panel";
import { ClosedBadge, StatusBadge } from "@/components/status-badge";
import { TagStrip } from "@/components/tag-picker";
import { TaskFilesPanel } from "@/components/task-files";
import { TimePanel } from "@/components/time-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Textarea } from "@/components/ui/textarea";
import { useToastManager } from "@/components/ui/toast";
import { timestamp } from "@/lib/format";
import {
  LEVEL_LABEL,
  PRIORITY_LABEL,
  STATUS_DOT,
  STATUS_LABEL,
  TASK_PRIORITIES,
  TASK_STATUSES,
  canEdit,
  personName,
  type Member,
  type Project,
  type Task,
  type TaskAccess,
  type TaskEvent,
  type TaskPriority,
  type TaskStatus,
} from "@/lib/types";

export default function TaskDetail() {
  const { orgId, taskId } = useParams<{ orgId: string; taskId: string }>();
  const { organisations, me, timer, refreshTimer } = useOutletContext<Shell>();
  const navigate = useNavigate();
  const toast = useToastManager();
  const org = organisations.find((o) => o.id === orgId) ?? null;

  const [task, setTask] = useState<Task | null>(null);
  const [accessInfo, setAccessInfo] = useState<TaskAccess | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [gone, setGone] = useState(false);
  // Comments can carry files, so posting one has to reach the Files panel.
  const [filesKey, setFilesKey] = useState(0);

  const load = useCallback(async () => {
    if (!orgId || !taskId) return;
    try {
      const t = await api<Task>(`/organisations/${orgId}/tasks/${taskId}`);
      setTask(t);
      const [acc, evs, ms, ps] = await Promise.all([
        api<TaskAccess>(`/organisations/${orgId}/tasks/${taskId}/access`),
        api<TaskEvent[]>(`/organisations/${orgId}/tasks/${taskId}/events`),
        api<Member[]>(`/organisations/${orgId}/members`),
        api<Project[]>(`/organisations/${orgId}/projects`),
      ]);
      setAccessInfo(acc);
      setEvents(evs);
      setMembers(ms);
      setProjects(ps);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setGone(true);
    }
  }, [orgId, taskId]);

  useEffect(() => {
    void load();
  }, [load]);

  const onCommentsChanged = useCallback(() => setFilesKey((k) => k + 1), []);

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
          // Access flows up read-only: you get the project's name for the
          // trail, not its other tasks and not a place in your project list.
          ...(task.project_name ? [{ label: task.project_name }] : []),
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
          // Only the owner (or an org admin) closes — resolved server-side and
          // sent as `can_close`, so the button isn't there for anyone else
          // rather than being there and 403-ing.
          task.can_close && (
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
          )
        }
      />

      <TagStrip
        orgId={org.id}
        taskId={task.id}
        tags={task.tags}
        editable={editable}
        onChanged={load}
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Details</CardTitle>
            </CardHeader>
            <CardContent>
              <Details task={task} orgId={org.id} editable={editable} onSaved={load} />
            </CardContent>
          </Card>

          {/* Above the thread: the files are part of what the task *is*, and
              a panel below a conversation that grows all day is a panel
              nobody finds twice. */}
          <TaskFilesPanel
            orgId={org.id}
            taskId={task.id}
            canEdit={editable}
            refreshKey={filesKey}
          />

          <PrivateNote orgId={org.id} taskId={task.id} />

          <CommentThread
            orgId={org.id}
            anchor="tasks"
            anchorId={task.id}
            onChanged={onCommentsChanged}
          />

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
        </div>

        <div className="space-y-4">
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
              {/* Five options doesn't need a filter, but a card where one
                  control opens differently from the four above it reads as a
                  bug. Same component, same behaviour. */}
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
            </CardContent>
          </Card>

          <ReminderPanel orgId={org.id} taskId={task.id} />

          <TimePanel
            orgId={org.id}
            taskId={task.id}
            meId={me?.id}
            timer={timer}
            // Reload the task too, not just the header clock: logging or
            // correcting time writes a `task_events` row, and the History card
            // is right there on the same screen. Refreshing one and not the
            // other leaves the trail looking like it didn't record anything.
            onTimerChanged={async () => {
              await refreshTimer();
              await load();
            }}
          />

          <TaskAccessCard
            task={task}
            orgId={org.id}
            access={accessInfo}
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

          {accessInfo.can_manage && (
            <Card>
              <CardContent className="pt-6">
                <Button
                  variant="destructive"
                  onClick={() =>
                    act(async () => {
                      await api(`/organisations/${org.id}/tasks/${task.id}`, {
                        method: "DELETE",
                      });
                      navigate(`/orgs/${org.id}/tasks`);
                    }, "Task deleted")
                  }
                >
                  <Trash2Icon />
                  Delete task
                </Button>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function Details({
  task,
  orgId,
  editable,
  onSaved,
}: {
  task: Task;
  orgId: string;
  editable: boolean;
  onSaved: () => Promise<void>;
}) {
  const toast = useToastManager();
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description ?? "");

  if (!editable) {
    return (
      <div className="space-y-2 text-sm">
        <p className={task.description ? "" : "text-muted-foreground"}>
          {task.description || "No description."}
        </p>
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
        <Label htmlFor="task-desc">Description</Label>
        <Textarea
          id="task-desc"
          rows={5}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
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
  onToggleHidden,
}: {
  task: Task;
  orgId: string;
  access: TaskAccess;
  /** Absent for anyone who isn't the owner — including org admins. */
  onToggleHidden?: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Who can see this</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {/* While hidden, the list below is not the answer to the question this
            card asks — so the card says so first and greys the list out,
            rather than showing names of people who currently see nothing. */}
        {task.is_hidden ? (
          <p className="text-muted-foreground">
            <span className="font-medium text-foreground">Only you.</span> Hiding overrides
            everything below — this task is invisible to the people listed, to anyone in its
            project, and to the organisation&rsquo;s admins.
          </p>
        ) : access.inherits_from_project ? (
          <p className="text-muted-foreground">
            Anyone who can see{" "}
            <Link
              to={`/orgs/${orgId}/projects/${task.project_id}`}
              className="font-medium text-foreground underline underline-offset-2"
            >
              {access.project_name}
            </Link>{" "}
            can see this task, at the same level.
          </p>
        ) : (
          <p className="text-muted-foreground">
            This task has no project, so only the people below can see it — not everyone in the
            organisation.
          </p>
        )}

        <dl className={`space-y-1 ${task.is_hidden ? "opacity-50" : ""}`}>
          <Row label="Owner" value={personName(access.owner)} />
          {access.action_required && (
            <Row label="Action required" value={personName(access.action_required)} />
          )}
          {access.grants.map((grant) => (
            <Row
              key={grant.id}
              label={grant.team ? `${grant.team.name} (team)` : personName(grant.user)}
              value={LEVEL_LABEL[grant.level]}
            />
          ))}
          {access.organisation_admins.map((admin) => (
            <Row key={admin.id} label={personName(admin)} value="Organisation admin" muted />
          ))}
        </dl>

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
