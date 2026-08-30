import { GitBranchIcon, XIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "@/api";
import { ClosedBadge, StatusBadge } from "@/components/status-badge";
import { TaskSearchPicker } from "@/components/task-search-picker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToastManager } from "@/components/ui/toast";
import type { SearchHit, TaskDependencies } from "@/lib/types";

/**
 * "Depends on" between tasks — purely informational, never enforced.
 *
 * Closing a task with open dependencies still works: the ask was visibility
 * ("to see if it's not blocking"), not a gate, and this codebase doesn't
 * invent enforcement beyond what's asked. See CLAUDE.md's Tasks section.
 *
 * Two lists, only one of them editable. `depends_on` is what this task is
 * waiting on — add and remove live here. `blocks` is the reverse: what's
 * waiting on *this* task, shown read-only, because editing it means editing
 * a *different* task's own list. A dependency the caller can't see comes
 * back with `task: null` from the API and renders as a muted placeholder
 * here — never its title or status.
 */
export function DependenciesPanel({
  orgId,
  taskId,
  canEdit,
  refreshKey,
}: {
  orgId: string;
  taskId: string;
  canEdit: boolean;
  refreshKey?: number;
}) {
  const toast = useToastManager();
  const [deps, setDeps] = useState<TaskDependencies | null>(null);

  const base = `/organisations/${orgId}/tasks/${taskId}/dependencies`;

  const load = useCallback(async () => {
    setDeps(await api<TaskDependencies>(base).catch(() => null));
  }, [base]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const fail = (err: unknown, title: string) => {
    const detail = err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
    toast.add({ title, description: detail });
  };

  const link = async (hit: SearchHit) => {
    try {
      await api(base, { method: "POST", body: JSON.stringify({ depends_on_task_id: hit.id }) });
      await load();
    } catch (err) {
      fail(err, "Couldn't link that task");
    }
  };

  const unlink = async (dependencyId: string) => {
    try {
      await api(`${base}/${dependencyId}`, { method: "DELETE" });
      await load();
    } catch (err) {
      fail(err, "Couldn't remove that link");
    }
  };

  if (deps !== null && deps.depends_on.length === 0 && deps.blocks.length === 0 && !canEdit) {
    return null;
  }

  const openCount = deps?.depends_on.filter((d) => d.task?.is_open).length ?? 0;
  const excludeIds = new Set([taskId, ...(deps?.depends_on.map((d) => d.task?.id ?? "") ?? [])]);

  return (
    <Card role="region" aria-label="Dependencies">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <GitBranchIcon className="size-4" />
          Depends on
          {deps && deps.depends_on.length > 0 && (
            <span className="font-mono text-xs font-normal text-muted-foreground">
              {openCount} open, {deps.depends_on.length - openCount} closed
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {deps?.depends_on.length ? (
          <ul className="space-y-1">
            {deps.depends_on.map((edge) => (
              <DependencyRow
                key={edge.id}
                orgId={orgId}
                edge={edge}
                canEdit={canEdit}
                onRemove={() => unlink(edge.id)}
              />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Nothing this task is waiting on.</p>
        )}

        {canEdit && (
          <TaskSearchPicker orgId={orgId} excludeTaskIds={excludeIds} onSelect={link} />
        )}

        {deps?.blocks.length ? (
          <div className="space-y-1 border-t pt-4">
            <p className="text-xs text-muted-foreground">
              Waiting on this task ({deps.blocks.length}):
            </p>
            <ul className="space-y-1">
              {deps.blocks.map((edge) => (
                <DependencyRow key={edge.id} orgId={orgId} edge={edge} canEdit={false} />
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function DependencyRow({
  orgId,
  edge,
  canEdit,
  onRemove,
}: {
  orgId: string;
  edge: TaskDependencies["depends_on"][number];
  canEdit: boolean;
  onRemove?: () => void;
}) {
  return (
    <li className="flex items-center gap-2 rounded-md border px-2 py-1.5">
      {edge.task ? (
        <>
          <Link
            to={`/orgs/${orgId}/tasks/${edge.task.id}`}
            className="min-w-0 flex-1 truncate text-sm hover:underline"
          >
            {edge.task.title}
          </Link>
          <StatusBadge status={edge.task.status} />
          <ClosedBadge isOpen={edge.task.is_open} />
        </>
      ) : (
        <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground italic">
          A task you don&rsquo;t have access to
        </span>
      )}
      {canEdit && onRemove && (
        <Button size="sm" variant="ghost" aria-label="Remove dependency" onClick={onRemove}>
          <XIcon />
        </Button>
      )}
    </li>
  );
}
