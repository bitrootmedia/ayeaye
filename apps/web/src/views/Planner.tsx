import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { CalendarDaysIcon, GripVerticalIcon, InboxIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router-dom";

import { ApiError, api } from "@/api";
import type { Shell } from "@/App";
import { EntityPicker, type PickerItem } from "@/components/entity-picker";
import { PageHeader } from "@/components/page-header";
import { PriorityGlyph } from "@/components/priority";
import { ClosedBadge } from "@/components/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { useToastManager } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import {
  PLANNER_BUCKETS,
  PLANNER_BUCKET_LABEL,
  canManageMembers,
  type Member,
  type PlannerBoard,
  type PlannerBucket,
  type PlannerEntry,
  type PlannerTask,
} from "@/lib/types";

/** The pool and every bucket, by one shared id space — a task's id, since it
 *  lives in exactly one place at a time. */
type ContainerId = "pool" | PlannerBucket;

const CONTAINERS: ContainerId[] = ["pool", ...PLANNER_BUCKETS];

function isContainerId(id: string): id is ContainerId {
  return (CONTAINERS as string[]).includes(id);
}

function containerOf(board: PlannerBoard, taskId: string): ContainerId | null {
  if (board.pool.some((t) => t.id === taskId)) return "pool";
  for (const bucket of PLANNER_BUCKETS) {
    if (board.buckets[bucket].some((e) => e.task.id === taskId)) return bucket;
  }
  return null;
}

/** Where a card should land: the midpoint of its new neighbours, or ±1000 at
 *  an end. Same no-resequencing philosophy as Task.position — a plain
 *  integer, computed once per drop, nothing server-side ever renumbers it. */
function positionFor(neighbours: { position: number }[], index: number): number {
  if (neighbours.length === 0) return 1000;
  if (index <= 0) return neighbours[0].position - 1000;
  if (index >= neighbours.length) return neighbours[neighbours.length - 1].position + 1000;
  return Math.floor((neighbours[index - 1].position + neighbours[index].position) / 2);
}

export default function Planner() {
  const { orgId } = useParams<{ orgId: string }>();
  const { organisations, me } = useOutletContext<Shell>();
  const toast = useToastManager();
  const org = organisations.find((o) => o.id === orgId) ?? null;

  const [members, setMembers] = useState<Member[]>([]);
  const [targetUserId, setTargetUserId] = useState<string | null>(null);
  const [board, setBoard] = useState<PlannerBoard | null>(null);
  const [activeTask, setActiveTask] = useState<PlannerTask | null>(null);

  const isAdmin = org ? canManageMembers(org.role) : false;
  const viewingSelf = targetUserId === null || targetUserId === me?.id;
  const qs = !viewingSelf && targetUserId ? `?user_id=${targetUserId}` : "";

  const load = useCallback(async () => {
    if (!orgId) return;
    setBoard(await api<PlannerBoard>(`/organisations/${orgId}/planner${qs}`));
  }, [orgId, qs]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!orgId || !isAdmin) return;
    void api<Member[]>(`/organisations/${orgId}/members`).then(setMembers);
  }, [orgId, isAdmin]);

  const people: PickerItem[] = useMemo(
    () => [
      { value: "self", label: "Me" },
      ...members
        .filter((m) => m.status === "active" && m.user_id && m.user_id !== me?.id)
        .map((m) => ({
          value: m.user_id!,
          label: m.display_name || m.email || "Unknown",
          hint: m.display_name ? (m.email ?? undefined) : undefined,
        })),
    ],
    [members, me],
  );

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const place = useCallback(
    async (taskId: string, bucket: PlannerBucket, position: number) => {
      await api(`/organisations/${orgId}/planner/${taskId}${qs}`, {
        method: "PUT",
        body: JSON.stringify({ bucket, position }),
      });
    },
    [orgId, qs],
  );

  const unplan = useCallback(
    async (taskId: string) => {
      await api(`/organisations/${orgId}/planner/${taskId}${qs}`, { method: "DELETE" });
    },
    [orgId, qs],
  );

  const onDragStart = (event: DragStartEvent) => {
    if (!board) return;
    const taskId = String(event.active.id);
    const from = containerOf(board, taskId);
    const task =
      from === "pool"
        ? board.pool.find((t) => t.id === taskId)
        : from
          ? board.buckets[from].find((e) => e.task.id === taskId)?.task
          : undefined;
    setActiveTask(task ?? null);
  };

  const onDragEnd = async (event: DragEndEvent) => {
    setActiveTask(null);
    const { active, over } = event;
    if (!board || !over) return;

    const taskId = String(active.id);
    const overId = String(over.id);
    const from = containerOf(board, taskId);
    const to = isContainerId(overId) ? overId : containerOf(board, overId);
    if (!from || !to) return;
    if (from === to && from === "pool") return; // pool order isn't persisted

    const task =
      from === "pool"
        ? board.pool.find((t) => t.id === taskId)
        : board.buckets[from].find((e) => e.task.id === taskId)?.task;
    if (!task) return;

    const snapshot = board;

    if (to === "pool") {
      // The early return above already ruled out from === to === "pool", so
      // `from` is a real bucket here.
      const sourceBucket = from as PlannerBucket;
      setBoard({
        ...board,
        pool: [...board.pool, task],
        buckets: {
          ...board.buckets,
          [sourceBucket]: board.buckets[sourceBucket].filter((e) => e.task.id !== taskId),
        },
      });
      try {
        await unplan(taskId);
      } catch {
        setBoard(snapshot);
        toast.add({ title: "Couldn't move that", description: "Try again." });
      }
      return;
    }

    // Destination is a bucket. `others` excludes the dragged task from
    // whichever list it's landing in, so index math never has to account for
    // its own old position colliding with its new one.
    const destOthers = board.buckets[to].filter((e) => e.task.id !== taskId);
    const overIndex = destOthers.findIndex((e) => e.task.id === overId);
    const insertIndex = overId === to ? destOthers.length : overIndex === -1 ? destOthers.length : overIndex;
    const position = positionFor(destOthers, insertIndex);
    const entry: PlannerEntry = { task, bucket: to, position };
    const newDest = [...destOthers.slice(0, insertIndex), entry, ...destOthers.slice(insertIndex)];

    setBoard({
      ...board,
      pool: from === "pool" ? board.pool.filter((t) => t.id !== taskId) : board.pool,
      buckets: {
        ...board.buckets,
        ...(from !== "pool" && from !== to
          ? { [from]: board.buckets[from].filter((e) => e.task.id !== taskId) }
          : {}),
        [to]: newDest,
      },
    });

    try {
      await place(taskId, to, position);
    } catch (err) {
      setBoard(snapshot);
      const detail =
        err instanceof ApiError && err.status === 404
          ? "That task isn't visible to this person any more."
          : "Try again.";
      toast.add({ title: "Couldn't move that", description: detail });
    }
  };

  if (!org) return null;

  return (
    <>
      <PageHeader
        title="Planner"
        description="Drag a task in from the left, or between buckets. Nobody else sees this unless you're an admin looking at someone else's."
        actions={
          isAdmin &&
          people.length > 1 && (
            <div className="w-56">
              <EntityPicker
                ariaLabel="Planning for"
                items={people}
                value={targetUserId ?? "self"}
                searchPlaceholder="Find a person…"
                onChange={(v) => setTargetUserId(v === "self" || !v ? null : v)}
              />
            </div>
          )
        }
      />

      {board === null ? (
        <div className="flex flex-1 items-center justify-center py-12">
          <Spinner />
        </div>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={onDragStart}
          onDragEnd={onDragEnd}
        >
          <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
            <Pool tasks={board.pool} />
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
              {PLANNER_BUCKETS.map((bucket) => (
                <Bucket key={bucket} bucket={bucket} entries={board.buckets[bucket]} />
              ))}
            </div>
          </div>
          <DragOverlay>{activeTask && <TaskCardBody task={activeTask} />}</DragOverlay>
        </DndContext>
      )}
    </>
  );
}

function Pool({ tasks }: { tasks: PlannerTask[] }) {
  const { setNodeRef, isOver } = useDroppable({ id: "pool" });
  return (
    <Card role="region" aria-label="Not planned yet">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <InboxIcon className="size-4" />
          Not planned yet
          <span className="font-mono text-sm font-normal text-muted-foreground">{tasks.length}</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <SortableContext items={tasks.map((t) => t.id)} strategy={verticalListSortingStrategy}>
          <div
            ref={setNodeRef}
            className={cn(
              "flex min-h-16 flex-col gap-2 rounded-lg p-1",
              isOver && "bg-accent/50 ring-1 ring-primary/40",
            )}
          >
            {tasks.length === 0 ? (
              <p className="p-2 text-sm text-muted-foreground">Everything open is planned.</p>
            ) : (
              tasks.map((task) => <TaskCard key={task.id} task={task} />)
            )}
          </div>
        </SortableContext>
      </CardContent>
    </Card>
  );
}

function Bucket({ bucket, entries }: { bucket: PlannerBucket; entries: PlannerEntry[] }) {
  const { setNodeRef, isOver } = useDroppable({ id: bucket });
  return (
    <Card role="region" aria-label={PLANNER_BUCKET_LABEL[bucket]}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <CalendarDaysIcon className="size-4" />
          {PLANNER_BUCKET_LABEL[bucket]}
          <span className="font-mono text-xs font-normal text-muted-foreground">
            {entries.length}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <SortableContext items={entries.map((e) => e.task.id)} strategy={verticalListSortingStrategy}>
          <div
            ref={setNodeRef}
            className={cn(
              "flex min-h-24 flex-col gap-2 rounded-lg p-1",
              isOver && "bg-accent/50 ring-1 ring-primary/40",
            )}
          >
            {entries.map((entry) => (
              <TaskCard key={entry.task.id} task={entry.task} />
            ))}
          </div>
        </SortableContext>
      </CardContent>
    </Card>
  );
}

function TaskCard({ task }: { task: PlannerTask }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: task.id,
  });
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(isDragging && "opacity-40")}
    >
      <TaskCardBody task={task} dragHandleProps={{ ...attributes, ...listeners }} />
    </div>
  );
}

/** Separated from `TaskCard` so the `DragOverlay` — which renders a copy that
 *  follows the pointer, outside any sortable context — can share the same
 *  markup without also carrying a live drag handle. */
function TaskCardBody({
  task,
  dragHandleProps,
}: {
  task: PlannerTask;
  dragHandleProps?: Record<string, unknown>;
}) {
  // Read directly rather than threaded down as a prop: this renders both
  // inside the sortable tree and, via DragOverlay, inside a portal — React
  // context (which useParams relies on) still flows through a portal, so
  // this is simpler than plumbing orgId through Pool/Bucket/TaskCard.
  const { orgId } = useParams<{ orgId: string }>();
  return (
    <div className="flex items-center gap-2 rounded-lg border bg-card p-2 shadow-sm">
      <button
        type="button"
        // dnd-kit's own sensors handle the actual pick-up; this is a visible,
        // keyboard-focusable target rather than the whole card, so tabbing
        // through a bucket doesn't feel like tabbing through buttons that do
        // nothing until you also happen to be over one.
        aria-label={`Move ${task.title}`}
        className="shrink-0 cursor-grab touch-none text-muted-foreground hover:text-foreground active:cursor-grabbing"
        {...dragHandleProps}
      >
        <GripVerticalIcon className="size-4" />
      </button>
      <PriorityGlyph priority={task.priority} />
      {/* A plain link, not a drag target — only the grip button above carries
          dnd-kit's listeners, so opening the task and moving it never fight
          over the same click. */}
      <Link
        to={`/orgs/${orgId}/tasks/${task.id}`}
        className={cn(
          "min-w-0 flex-1 truncate text-sm hover:underline",
          !task.is_open && "text-muted-foreground line-through",
        )}
      >
        {task.title}
      </Link>
      <ClosedBadge isOpen={task.is_open} />
    </div>
  );
}
