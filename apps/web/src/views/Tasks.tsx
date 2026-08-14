import {
  CircleDotIcon,
  Columns3Icon,
  EyeOffIcon,
  LayoutGridIcon,
  ListIcon,
  PlusIcon,
  SignalIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useOutletContext, useParams, useSearchParams } from "react-router-dom";

import { ApiError, api } from "@/api";
import type { Shell } from "@/App";
import { EntityPicker, type PickerItem } from "@/components/entity-picker";
import { PageHeader } from "@/components/page-header";
import { PriorityGlyph } from "@/components/priority";
import { ClosedBadge, StatusBadge } from "@/components/status-badge";
import { TagChip } from "@/components/tag-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { Textarea } from "@/components/ui/textarea";
import { useToastManager } from "@/components/ui/toast";
import {
  PRIORITY_LABEL,
  STATUS_LABEL,
  TASK_PRIORITIES,
  TASK_STATUSES,
  personName,
  type Project,
  type Tag,
  type Task,
  type TaskPriority,
  type TaskStatus,
} from "@/lib/types";

const NO_PROJECT = "__loose__";

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
  const view = params.get("view") === "list" ? "list" : "board";
  const groupBy = params.get("group") === "priority" ? "priority" : "status";
  const showClosed = params.get("closed") === "1";

  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    if (!orgId) return;
    const query = new URLSearchParams({ include_closed: String(showClosed) });
    if (projectFilter === NO_PROJECT) query.set("loose", "true");
    else if (projectFilter) query.set("project_id", projectFilter);
    // Asking for a tag by name is asking for its tasks, off-board or not.
    if (tagFilter) query.set("tag_id", tagFilter);
    const [ts, ps, gs] = await Promise.all([
      api<Task[]>(`/organisations/${orgId}/tasks?${query}`),
      api<Project[]>(`/organisations/${orgId}/projects`),
      api<Tag[]>(`/organisations/${orgId}/tags`),
    ]);
    setTasks(ts);
    setProjects(ps);
    setTags(gs);
  }, [orgId, projectFilter, tagFilter, showClosed]);

  useEffect(() => {
    void load().catch(() => setTasks([]));
  }, [load]);

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
                aria-label="Group the board by status or priority"
                onClick={() => setParam("group", groupBy === "status" ? "priority" : null)}
              >
                {groupBy === "status" ? <SignalIcon /> : <Columns3Icon />}
                {groupBy === "status" ? "By priority" : "By status"}
              </Button>
            )}
            <Button
              variant="ghost"
              onClick={() => setParam("view", view === "board" ? "list" : "board")}
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
      </div>

      {/* Off-board tasks are absent unless you asked for one by name, so the
          screen says which mode it's in rather than leaving a silent gap. */}
      {offBoardTag && (
        <p className="text-sm text-muted-foreground">
          Showing <span className="font-medium text-foreground">{offBoardTag.name}</span>, which is
          kept off the board. These don&rsquo;t appear in the normal view.
        </p>
      )}

      {tasks === null ? (
        <div className="flex flex-1 items-center justify-center py-12">
          <Spinner />
        </div>
      ) : tasks.length === 0 ? (
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
        <Board orgId={org.id} tasks={tasks} groupBy={groupBy} />
      ) : (
        <TaskList orgId={org.id} tasks={tasks} />
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
  tasks,
  groupBy,
}: {
  orgId: string;
  tasks: Task[];
  groupBy: "status" | "priority";
}) {
  // Both arrangements are "one column per value of a fixed enum", so the only
  // thing that differs is which key and what the heading looks like. Six
  // priority columns against five status ones — the grid takes both.
  const columns =
    groupBy === "status"
      ? TASK_STATUSES.map((status) => ({
          key: status,
          heading: <StatusBadge status={status} />,
          items: tasks.filter((t) => t.status === status),
        }))
      : TASK_PRIORITIES.map((priority) => ({
          key: priority,
          heading: (
            <span className="flex items-center gap-1.5 text-sm font-medium">
              <PriorityGlyph priority={priority} />
              {PRIORITY_LABEL[priority]}
            </span>
          ),
          items: tasks.filter((t) => t.priority === priority),
        }));

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
      {columns.map((column) => (
        <div key={column.key} className="flex flex-col gap-2 rounded-xl bg-muted/40 p-2">
          <div className="flex items-center justify-between px-1 py-1">
            {column.heading}
            <span className="font-mono text-xs text-muted-foreground">{column.items.length}</span>
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
              {groupBy === "priority" && <StatusBadge status={task.status} />}
              <TaskMeta task={task} />
            </Link>
          ))}
          {column.items.length === 0 && (
            <p className="px-1 py-2 text-xs text-muted-foreground">Nothing here.</p>
          )}
        </div>
      ))}
    </div>
  );
}

function TaskList({ orgId, tasks }: { orgId: string; tasks: Task[] }) {
  return (
    <div className="divide-y rounded-xl border bg-card">
      {tasks.map((task) => (
        <Link
          key={task.id}
          to={`/orgs/${orgId}/tasks/${task.id}`}
          className="flex flex-wrap items-center gap-3 p-3 transition-colors hover:bg-accent/50"
        >
          <StatusBadge status={task.status} />
          <PriorityGlyph priority={task.priority} />
          <span className="min-w-0 flex-1 truncate text-sm font-medium">{task.title}</span>
          <HiddenMark task={task} />
          <ClosedBadge isOpen={task.is_open} />
          <TaskMeta task={task} />
        </Link>
      ))}
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

function TaskMeta({ task }: { task: Task }) {
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
      {task.action_required && (
        <Badge variant="outline" className="gap-1.5 text-primary">
          <span className="size-1.5 rounded-full bg-primary" />
          {personName(task.action_required)}
        </Badge>
      )}
    </div>
  );
}

function NewTaskDialog({
  open,
  onOpenChange,
  orgId,
  projects,
  defaultProject,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgId: string;
  projects: Project[];
  defaultProject: string;
  onCreated: () => Promise<void>;
}) {
  const toast = useToastManager();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<TaskStatus>("todo");
  const [priority, setPriority] = useState<TaskPriority>("normal");
  const [projectId, setProjectId] = useState<string | null>(defaultProject || null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) setProjectId(defaultProject || null);
  }, [open, defaultProject]);

  // Only projects you can edit — filing work into someone's project changes
  // what they see, so a viewer shouldn't be able to. The API enforces it; this
  // just avoids offering an option that would 403.
  const projectItems: PickerItem[] = projects
    .filter((p) => p.access !== "read" && !p.archived)
    .map((p) => ({ value: p.id, label: p.name, hint: p.project_group_name ?? undefined }));
  const statusItems: PickerItem[] = TASK_STATUSES.map((s) => ({ value: s, label: STATUS_LABEL[s] }));
  const priorityItems: PickerItem[] = TASK_PRIORITIES.map((p) => ({
    value: p,
    label: PRIORITY_LABEL[p],
    icon: <PriorityGlyph priority={p} />,
  }));

  const submit = async () => {
    if (!title.trim() || busy) return;
    setBusy(true);
    try {
      await api(`/organisations/${orgId}/tasks`, {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          description: description.trim() || null,
          status,
          priority,
          project_id: projectId,
        }),
      });
      setTitle("");
      setDescription("");
      setStatus("todo");
      setPriority("normal");
      onOpenChange(false);
      await onCreated();
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "Couldn't create that", description: detail });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New task</DialogTitle>
          <DialogDescription>
            You&rsquo;ll own it, which means you&rsquo;re the one who can close it.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="task-title">Title</Label>
            <Input
              id="task-title"
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="task-description">Description</Label>
            <Textarea
              id="task-description"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="task-status">Status</Label>
              <EntityPicker
                id="task-status"
                ariaLabel="Status"
                items={statusItems}
                value={status}
                searchPlaceholder="Filter…"
                onChange={(v) => v && setStatus(v as TaskStatus)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="task-priority">Priority</Label>
              <EntityPicker
                id="task-priority"
                ariaLabel="Priority"
                items={priorityItems}
                value={priority}
                searchPlaceholder="Filter…"
                onChange={(v) => v && setPriority(v as TaskPriority)}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="task-project">Project</Label>
            <EntityPicker
              id="task-project"
              ariaLabel="Project"
              items={projectItems}
              value={projectId}
              placeholder="No project"
              emptyLabel="No project"
              searchPlaceholder="Find a project…"
              onChange={setProjectId}
            />
          </div>
          {!projectId && (
            /* The loose-task rule, said where the decision is being made
               rather than in a help page nobody opens. */
            <p className="text-xs text-muted-foreground">
              A task with no project is visible only to you, anyone you share it with, and the
              organisation&rsquo;s admins — not to everyone in the organisation.
            </p>
          )}
        </div>
        <DialogFooter>
          <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
          <Button onClick={submit} disabled={busy || !title.trim()}>
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
