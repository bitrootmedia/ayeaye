import { InboxIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router-dom";

import { api, apiWithHeaders } from "@/api";
import type { Shell } from "@/App";
import { EntityPicker, type PickerItem } from "@/components/entity-picker";
import { PageHeader } from "@/components/page-header";
import { PriorityGlyph } from "@/components/priority";
import { StatusBadge } from "@/components/status-badge";
import { TagChip } from "@/components/tag-picker";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToastManager } from "@/components/ui/toast";
import { ago } from "@/lib/format";
import {
  PRIORITY_LABEL,
  TASK_PRIORITIES,
  canEdit,
  personName,
  type Member,
  type Task,
  type TaskPriority,
} from "@/lib/types";

/** Rows per page, and how much "Show more" adds — the task list's own PAGE. */
const PAGE = 100;

/**
 * Triage: open tasks nobody has been asked to act on.
 *
 * The queue this product didn't have a screen for. Every other task surface
 * answers "what's mine" (the dashboard's escalation cards, the planner) or
 * "what's everything" (the list, the board); this one answers the question in
 * between — what has fallen between the two, because nobody has picked it up.
 *
 * **Everything you can see, not just what you own.** That's the whole point:
 * a triage queue scoped to your own tasks is a personal follow-up list, and
 * the work most likely to be forgotten is the work nobody has claimed. An
 * organisation admin therefore sees the organisation's whole unassigned pile,
 * which is exactly the escape hatch admin rank exists for elsewhere.
 *
 * **A row leaves the moment you assign it**, rather than sitting there greyed
 * out or waiting for a refetch — the list is defined by "action-required is
 * unset", so a task that now has one is no longer a member of it. Removing it
 * locally rather than reloading the page keeps your place in a long queue,
 * which is the difference between working through one and starting it again
 * every time.
 */
export default function Triage() {
  const { orgId } = useParams<{ orgId: string }>();
  const { organisations } = useOutletContext<Shell>();
  const toast = useToastManager();
  const org = organisations.find((o) => o.id === orgId) ?? null;

  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(PAGE);
  const [members, setMembers] = useState<Member[]>([]);
  // Which row is mid-save. Keyed by task id rather than a single boolean:
  // assigning one task must not freeze the picker on every other row.
  const [saving, setSaving] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!orgId) return;
    const res = await apiWithHeaders<Task[]>(
      `/organisations/${orgId}/tasks?action_required_unset=true&limit=${limit}`,
    );
    setTasks(res.data);
    setTotal(Number(res.headers.get("X-Total-Count") ?? res.data.length));
  }, [orgId, limit]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!orgId) return;
    void api<Member[]>(`/organisations/${orgId}/members`).then(setMembers);
  }, [orgId]);

  // The email is the hint line, and it's searched as well as shown — two
  // people called Jan is the ordinary case, not the edge one. Same shape as
  // the task screen's own picker, deliberately: one control that behaves the
  // same wherever you meet it.
  const people: PickerItem[] = useMemo(
    () =>
      members
        .filter((m) => m.status === "active" && m.user_id)
        .map((m) => ({
          value: m.user_id!,
          label: m.display_name || m.email || "Unknown",
          hint: m.display_name ? (m.email ?? undefined) : undefined,
        })),
    [members],
  );

  /**
   * Unlike assigning, re-prioritising does **not** take the row out of the
   * queue — the task still has nobody on it, which is the only thing this
   * list is about. So the row is patched in place rather than removed, and
   * triage stays a two-part judgement: how urgent is this, and who takes it.
   *
   * **The row doesn't jump to its new place in the order, either**, even
   * though the queue is sorted priority-first and it now belongs elsewhere.
   * Re-sorting under the pointer moves the next row you were about to reach
   * for, which is the same "never yank something out from under the person
   * mid-click" rule the task screen's own panels follow. The order is right
   * again on the next load, and nothing downstream reads it.
   *
   * No toast, unlike assigning: the glyph changes where you're already
   * looking, so saying so as well is noise. Assigning earns one because the
   * row vanishes and that needs explaining.
   */
  async function reprioritise(task: Task, priority: string | null) {
    if (!orgId || !priority || priority === task.priority) return;
    setSaving(task.id);
    try {
      await api(`/organisations/${orgId}/tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({ priority }),
      });
      setTasks((current) =>
        (current ?? []).map((t) =>
          t.id === task.id ? { ...t, priority: priority as TaskPriority } : t,
        ),
      );
    } catch {
      toast.add({
        title: "Couldn't change that priority",
        description: "Try again in a moment.",
      });
    } finally {
      setSaving(null);
    }
  }

  async function assign(task: Task, userId: string | null) {
    if (!orgId || !userId) return;
    setSaving(task.id);
    try {
      await api(`/organisations/${orgId}/tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({ action_required_user_id: userId }),
      });
      const name = people.find((p) => p.value === userId)?.label ?? "them";
      // Gone from the queue, not greyed out in it — see the component note.
      setTasks((current) => (current ?? []).filter((t) => t.id !== task.id));
      setTotal((n) => Math.max(0, n - 1));
      toast.add({
        title: "Assigned",
        description: `${task.title} — ${name} is now action-required.`,
      });
    } catch {
      toast.add({ title: "Couldn't assign that one", description: "Try again in a moment." });
    } finally {
      setSaving(null);
    }
  }

  if (!org) return null;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        crumbs={[{ label: org.name, to: `/orgs/${org.id}` }]}
        title="Triage"
        description="Open tasks nobody has been asked to act on. Set how urgent each one is, and
          pick who should — naming somebody takes it out of the queue."
      />

      {tasks === null ? (
        <Spinner />
      ) : tasks.length === 0 ? (
        <EmptyQueue />
      ) : (
        <>
          <div className="overflow-x-auto rounded-xl border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Task</TableHead>
                  <TableHead>Project</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Priority</TableHead>
                  <TableHead>Owner</TableHead>
                  <TableHead>Action required</TableHead>
                  <TableHead>Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tasks.map((task) => (
                  <TableRow key={task.id}>
                    <TableCell className="max-w-72">
                      <Link
                        to={`/orgs/${org.id}/tasks/${task.id}`}
                        className="flex items-center gap-2 font-medium hover:underline"
                      >
                        <span className="truncate">{task.title}</span>
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
                    <TableCell className="w-44">
                      {/* An EntityPicker rather than a Select, matching the
                          people picker beside it — a row where one control
                          opens differently from the one next to it reads as
                          a bug. Read-only viewers keep the plain glyph. */}
                      {canEdit(task.access) ? (
                        <EntityPicker
                          ariaLabel={`Priority for ${task.title}`}
                          items={TASK_PRIORITIES.map((p) => ({
                            value: p,
                            label: PRIORITY_LABEL[p],
                            icon: <PriorityGlyph priority={p} />,
                          }))}
                          value={task.priority}
                          searchPlaceholder="Filter…"
                          disabled={saving === task.id}
                          onChange={(v) => void reprioritise(task, v)}
                        />
                      ) : (
                        <PriorityGlyph priority={task.priority} withLabel />
                      )}
                    </TableCell>
                    <TableCell className="max-w-40 truncate">
                      {task.owner ? personName(task.owner) : "—"}
                    </TableCell>
                    <TableCell className="w-56">
                      {/* Read-only access is enough to *see* a task here and
                          not enough to reassign it, so the picker is simply
                          absent rather than present and 403ing. */}
                      {canEdit(task.access) ? (
                        <EntityPicker
                          ariaLabel={`Action required for ${task.title}`}
                          items={people}
                          value={null}
                          onChange={(v) => void assign(task, v)}
                          placeholder="Nobody"
                          searchPlaceholder="Find a person…"
                          disabled={saving === task.id}
                        />
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {ago(task.updated_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>
              {/* Says what the page is a page *of* — the same honesty the
                  task list's own pager keeps. */}
              Showing {tasks.length} of {total}
            </span>
            {tasks.length < total && (
              <Button variant="outline" size="sm" onClick={() => setLimit((n) => n + PAGE)}>
                Show more
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/** An empty triage queue is good news, so it reads as good news rather than
 *  as a screen that failed to load. */
function EmptyQueue() {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-12 text-center">
      <InboxIcon className="size-8 text-muted-foreground" />
      <p className="font-medium">Nothing to triage</p>
      <p className="max-w-sm text-sm text-muted-foreground">
        Every open task you can see has somebody action-required. New work turns up here as soon
        as it lands without one.
      </p>
    </div>
  );
}
