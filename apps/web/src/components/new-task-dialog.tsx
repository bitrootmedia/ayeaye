import { ExternalLinkIcon, TriangleAlertIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api } from "@/api";
import { EntityPicker, type PickerItem } from "@/components/entity-picker";
import { PriorityGlyph } from "@/components/priority";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToastManager } from "@/components/ui/toast";
import {
  PRIORITY_LABEL,
  STATUS_LABEL,
  TASK_PRIORITIES,
  TASK_STATUSES,
  type Project,
  type SearchHit,
  type Task,
  type TaskPriority,
  type TaskStatus,
} from "@/lib/types";

/** How long to wait after a keystroke before checking for duplicates — same
 *  idiom and constant as the search palette's own debounce. */
const DEBOUNCE_MS = 250;

/**
 * The New Task dialog. Lives here, not in `views/Tasks.tsx`, because a task
 * needs to be startable from anywhere — the header carries its own trigger
 * next to search, so this can't be a view-local component with a view-local
 * `projects` list it assumes is already loaded.
 *
 * **Three things that only make sense together, so they arrived together:**
 *
 * 1. **Duplicate detection is now live, not gated behind a first Create
 *    press.** It used to be the "type it again to mean it" shape a delete
 *    confirmation uses — press once to check, press again to confirm. That
 *    reads wrong once the same check runs continuously while you type: the
 *    warning is already on screen by the time you reach for Create, so a
 *    second press asking you to confirm what you already read is a press
 *    that confirms nothing new. Create now always creates, first press,
 *    **and never waits on the debounced check to settle** — the duplicate
 *    list is a courtesy read while you're still typing, not a gate the
 *    create action depends on.
 * 2. **Unsaved changes are protected.** `dirty` is true the moment title or
 *    description has anything in it. Every one of Base UI's own close paths
 *    — Escape, a backdrop click, the corner X — and the Cancel button all
 *    route through the same `onOpenChange`, so wrapping it once catches all
 *    of them: dirty asks first, in a small nested confirm; clean closes
 *    immediately.
 * 3. **Every close that isn't "keep editing" clears the form.** Before this,
 *    only a successful submit reset the fields — Cancel left them for the
 *    next person to open the dialog to find. `reset()` is the one function
 *    both paths call.
 */
export function NewTaskDialog({
  open,
  onOpenChange,
  orgId,
  projects: projectsProp,
  defaultProject = "",
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgId: string;
  /** Pass this when the caller already has the list loaded (the Tasks
   *  screen does, for its own filters) to skip a redundant fetch. Omitted
   *  entirely by a caller — like the header trigger — that has no reason to
   *  have loaded projects otherwise; the dialog fetches its own on open. */
  projects?: Project[];
  defaultProject?: string;
  onCreated?: () => Promise<void> | void;
}) {
  const toast = useToastManager();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<TaskStatus>("todo");
  const [priority, setPriority] = useState<TaskPriority>("normal");
  const [projectId, setProjectId] = useState<string | null>(defaultProject || null);
  const [busy, setBusy] = useState(false);
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);

  const [ownProjects, setOwnProjects] = useState<Project[]>([]);
  const projects = projectsProp ?? ownProjects;

  // null: not checked for the current title yet (or title is empty).
  const [similar, setSimilar] = useState<SearchHit[] | null>(null);
  const [checkingSimilar, setCheckingSimilar] = useState(false);
  // Same guard as the search palette: requests can return out of order, and
  // only the newest answer may write to state.
  const seq = useRef(0);
  const inflight = useRef<AbortController | null>(null);

  useEffect(() => {
    if (open) setProjectId(defaultProject || null);
  }, [open, defaultProject]);

  useEffect(() => {
    if (open && !projectsProp) {
      api<Project[]>(`/organisations/${orgId}/projects`)
        .then(setOwnProjects)
        .catch(() => setOwnProjects([]));
    }
  }, [open, orgId, projectsProp]);

  // Live duplicate check. Debounced and sequence-checked exactly like search
  // — see that component's own docstring for why both are load-bearing.
  useEffect(() => {
    const q = title.trim();
    if (!q) {
      inflight.current?.abort();
      setSimilar(null);
      setCheckingSimilar(false);
      return;
    }
    setCheckingSimilar(true);
    const mine = ++seq.current;
    const timer = setTimeout(async () => {
      inflight.current?.abort();
      const controller = new AbortController();
      inflight.current = controller;
      try {
        const found = await api<{ hits: SearchHit[] }>(
          `/organisations/${orgId}/tasks/similar?q=${encodeURIComponent(q)}`,
          { signal: controller.signal },
        );
        if (mine !== seq.current) return;
        setSimilar(found.hits);
      } catch {
        // A failed check must never block creating the task — it's a
        // courtesy read, not a gate the feature depends on. An abort is the
        // normal case here (a newer keystroke superseded this request), not
        // a failure worth reporting as one.
        if (mine === seq.current) setSimilar([]);
      } finally {
        if (mine === seq.current) setCheckingSimilar(false);
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [title, orgId]);

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

  // Title or description carrying typed prose is what's actually at risk of
  // being lost — status/priority/project are one click to redo and aren't
  // what "unsaved changes" means to whoever typed this.
  const dirty = title.trim() !== "" || description.trim() !== "";

  const reset = useCallback(() => {
    setTitle("");
    setDescription("");
    setStatus("todo");
    setPriority("normal");
    setProjectId(defaultProject || null);
    setSimilar(null);
  }, [defaultProject]);

  const requestClose = useCallback(() => {
    if (dirty) {
      setConfirmingDiscard(true);
      return;
    }
    reset();
    onOpenChange(false);
  }, [dirty, reset, onOpenChange]);

  // Every one of Base UI's own close paths — Escape, a backdrop click, the
  // corner X, and Cancel (a DialogClose) — call this. Wrapping it once is
  // what makes the dirty-check apply to all of them without special-casing
  // any single button.
  const handleOpenChange = (next: boolean) => {
    if (next) onOpenChange(true);
    else requestClose();
  };

  const submit = async () => {
    if (!title.trim() || busy) return;
    setBusy(true);
    try {
      const created = await api<Task>(`/organisations/${orgId}/tasks`, {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          description: description.trim() || null,
          status,
          priority,
          project_id: projectId,
        }),
      });
      reset();
      onOpenChange(false);
      await onCreated?.();
      // The dialog deliberately doesn't jump to the task it just made — you're
      // usually adding several in a row — so this is the only way back to it
      // without hunting through the list. Ten seconds, not the default five:
      // it's the one toast in the product somebody might read *after* typing
      // the next task's title rather than the instant it appears.
      toast.add({
        title: `Task "${created.title}" was created`,
        timeout: 10_000,
        actionProps: {
          children: "Open",
          onClick: () => navigate(`/orgs/${orgId}/tasks/${created.id}`),
        },
      });
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "Couldn't create that", description: detail });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        {/* A bounded column, not the default grid: the description grows
            with what you type (`Textarea` is `field-sizing-content`), and
            the whole dialog used to grow with it until the title and the
            Create button were both off-screen. Now only the middle
            scrolls — `DialogContent`'s own `max-h` catches anything that
            still doesn't fit. */}
        <DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col overflow-hidden">
          <DialogHeader className="shrink-0">
            <DialogTitle className="flex items-center gap-2">
              New task
              {dirty && (
                <span className="font-sans text-xs font-normal text-muted-foreground">
                  · Unsaved changes
                </span>
              )}
            </DialogTitle>
            <DialogDescription>
              You&rsquo;ll own it, which means you&rsquo;re the one who can close it.
            </DialogDescription>
          </DialogHeader>
          {/* `DialogContent` is itself `display: grid`, and a grid item's
              default `min-width: auto` means it won't shrink below its own
              content's min-content width — so an unbroken long string
              anywhere inside (a duplicate task's title, below) silently
              overflows the dialog's own `max-w-sm` box rather than wrapping
              or truncating. `min-w-0` here is what lets the `truncate`
              further down actually take effect instead of being overflowed
              past before it gets the chance. */}
          {/* `min-h-0` is what actually makes this scroll: a flex child's
              default `min-height: auto` floors it at its own content's
              height, so `flex-1` alone would let it push the footer out
              of the dialog instead of scrolling — the vertical twin of
              the `min-w-0` note above. `-mx-1 px-1` keeps focus rings on
              the inputs from being clipped by the new scroll container. */}
          <div className="min-w-0 min-h-0 flex-1 -mx-1 space-y-4 overflow-y-auto px-1">
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
            {title.trim() !== "" && checkingSimilar && similar === null && (
              <p className="text-xs text-muted-foreground">Checking for similar tasks…</p>
            )}
            {title.trim() !== "" && similar !== null && similar.length > 0 && (
              <div
                role="region"
                aria-label="Possible duplicates"
                className="space-y-2 rounded-lg border border-status-review/40 bg-status-review/5 p-3"
              >
                <p className="flex items-center gap-1.5 text-sm font-medium">
                  <TriangleAlertIcon className="size-4 text-status-review" />
                  Similar tasks already exist
                </p>
                <ul className="space-y-1">
                  {similar.slice(0, 5).map((hit) => (
                    <li key={hit.id}>
                      <a
                        href={`/orgs/${orgId}/tasks/${hit.id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex min-w-0 items-center gap-1.5 text-sm text-foreground hover:underline"
                      >
                        <span className="min-w-0 truncate">
                          {hit.title}
                          {hit.inactive && (
                            <span className="text-muted-foreground"> (closed)</span>
                          )}
                        </span>
                        <ExternalLinkIcon className="size-3 shrink-0 text-muted-foreground" />
                      </a>
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-muted-foreground">
                  You can still create this one — Create doesn&rsquo;t wait on this check.
                </p>
              </div>
            )}
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
          <DialogFooter className="shrink-0">
            <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
            <Button onClick={submit} disabled={busy || !title.trim()}>
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmingDiscard} onOpenChange={setConfirmingDiscard}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Discard this task?</DialogTitle>
            <DialogDescription>
              What you&rsquo;ve typed hasn&rsquo;t been saved. Closing now throws it away.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="ghost" />}>Keep editing</DialogClose>
            <Button
              variant="destructive"
              onClick={() => {
                setConfirmingDiscard(false);
                reset();
                onOpenChange(false);
              }}
            >
              Discard
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
