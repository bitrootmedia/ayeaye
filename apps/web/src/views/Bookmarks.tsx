import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  BookmarkIcon,
  ExternalLinkIcon,
  GripVerticalIcon,
  PencilIcon,
  PinIcon,
  PinOffIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useOutletContext, useParams } from "react-router-dom";

import { ApiError, api } from "@/api";
import type { Shell } from "@/App";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { useToastManager } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { canPinBookmark, type Bookmark } from "@/lib/types";

/** Where a row should land: the midpoint of its new neighbours, or ±1000 at
 *  an end. The same plain-integer, no-resequencing convention the Planner
 *  and `Task.position` already use — computed once per drop, and nothing
 *  server-side ever renumbers a list. */
function positionFor(neighbours: Bookmark[], index: number): number {
  if (neighbours.length === 0) return 1000;
  if (index <= 0) return neighbours[0].position - 1000;
  if (index >= neighbours.length) return neighbours[neighbours.length - 1].position + 1000;
  return Math.floor((neighbours[index - 1].position + neighbours[index].position) / 2);
}

/** The link text. `description` is the label; a bookmark saved without one
 *  falls back to its URL rather than rendering an empty anchor nobody can
 *  click. */
const labelOf = (bookmark: Bookmark) => bookmark.description || bookmark.url;

const errorDetail = (err: unknown) =>
  err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";

/**
 * Bookmarks: the organisation's own shelf of links.
 *
 * **Shared, unlike Sparks or the notepad** — every member reads the same rows
 * in the same order, which is the whole reason an order is worth keeping.
 * Three different bars, all resolved server-side (`services/bookmarks.py`):
 * any member adds and reorders, whoever added a row (or an org admin) edits
 * and removes it, and **only an organisation owner pins** — the one
 * capability an admin doesn't have outside deleting the organisation itself.
 *
 * **Pinned rows are their own list, not a flag on one long one**, and that
 * is a correctness point rather than a layout preference: the server sorts
 * every pinned row ahead of every unpinned one whatever its position, so a
 * single sortable list would let somebody drop an unpinned row above a
 * pinned one and watch it snap straight back. Two `SortableContext`s, no
 * dragging between them — the way a row changes group is the pin button.
 */
export default function Bookmarks() {
  const { orgId } = useParams<{ orgId: string }>();
  const { organisations } = useOutletContext<Shell>();
  const toast = useToastManager();
  const org = organisations.find((o) => o.id === orgId) ?? null;
  const canPin = org ? canPinBookmark(org.role) : false;

  const [bookmarks, setBookmarks] = useState<Bookmark[] | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    if (!orgId) return;
    setBookmarks(await api<Bookmark[]>(`/organisations/${orgId}/bookmarks`).catch(() => []));
  }, [orgId]);

  useEffect(() => {
    void load();
  }, [load]);

  const pinned = useMemo(() => bookmarks?.filter((b) => b.pinned) ?? [], [bookmarks]);
  const rest = useMemo(() => bookmarks?.filter((b) => !b.pinned) ?? [], [bookmarks]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    // Not a nicety: it is also how `bookmarks.spec.ts` drives a reorder,
    // for the reason `planner.spec.ts` documents — dnd-kit's pointer sensor
    // is genuinely flaky to script through synthetic mouse movement.
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const save = async (id: string, fields: { url?: string; description?: string }) => {
    try {
      const updated = await api<Bookmark>(`/organisations/${orgId}/bookmarks/${id}`, {
        method: "PATCH",
        body: JSON.stringify(fields),
      });
      setBookmarks((rows) => rows?.map((b) => (b.id === id ? updated : b)) ?? rows);
      toast.add({ title: "Bookmark saved" });
    } catch (err) {
      toast.add({ title: "Couldn't save that", description: errorDetail(err) });
    }
  };

  const remove = async (bookmark: Bookmark) => {
    // Optimistic: a link is cheap to re-add, and a failed request just means
    // the row comes back on the next load.
    setBookmarks((rows) => rows?.filter((b) => b.id !== bookmark.id) ?? rows);
    try {
      await api(`/organisations/${orgId}/bookmarks/${bookmark.id}`, { method: "DELETE" });
    } catch (err) {
      toast.add({ title: "Couldn't remove that", description: errorDetail(err) });
      await load();
    }
  };

  const togglePin = async (bookmark: Bookmark) => {
    try {
      await api(`/organisations/${orgId}/bookmarks/${bookmark.id}/pinned`, {
        method: "POST",
        body: JSON.stringify({ pinned: !bookmark.pinned }),
      });
      // Reloaded rather than patched in place: pinning moves the row between
      // the two lists, and its place in the one it lands in is the server's
      // ordering to state, not ours to guess.
      await load();
      toast.add({ title: bookmark.pinned ? "Unpinned" : "Pinned for everyone" });
    } catch (err) {
      toast.add({ title: "Couldn't change that", description: errorDetail(err) });
    }
  };

  const onDragEnd = async ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const activeId = String(active.id);
    const overId = String(over.id);
    // Which of the two lists — a drag never crosses them, so whichever holds
    // the row being moved is the one being reordered.
    const group = pinned.some((b) => b.id === activeId) ? pinned : rest;
    const from = group.findIndex((b) => b.id === activeId);
    const to = group.findIndex((b) => b.id === overId);
    if (from < 0 || to < 0) return;

    const moved = arrayMove(group, from, to);
    // The neighbours the row lands between, which is the list *without* it —
    // `arrayMove`'s result at `to` is exactly an insert into this at `to`.
    const position = positionFor(
      group.filter((b) => b.id !== activeId),
      to,
    );
    const reordered = moved.map((b) => (b.id === activeId ? { ...b, position } : b));
    setBookmarks(group === pinned ? [...reordered, ...rest] : [...pinned, ...reordered]);

    try {
      await api(`/organisations/${orgId}/bookmarks/${activeId}/position`, {
        method: "POST",
        body: JSON.stringify({ position }),
      });
    } catch (err) {
      toast.add({ title: "Couldn't reorder that", description: errorDetail(err) });
      await load();
    }
  };

  if (!org) return null;

  return (
    <>
      <PageHeader
        crumbs={[{ label: org.name, to: `/orgs/${org.id}` }, { label: "Bookmarks" }]}
        title="Bookmarks"
        description={
          canPin
            ? "Links the whole organisation shares. Anyone can add one and put the list in order; pinning is yours alone."
            : "Links the whole organisation shares. Anyone can add one and put the list in order."
        }
        actions={
          <Button onClick={() => setAdding(true)}>
            <PlusIcon />
            Add bookmark
          </Button>
        }
      />

      {bookmarks === null ? (
        <div className="flex flex-1 items-center justify-center py-12">
          <Spinner />
        </div>
      ) : bookmarks.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <BookmarkIcon />
            </EmptyMedia>
            <EmptyTitle>No bookmarks yet</EmptyTitle>
            <EmptyDescription>
              The staging site, the shared drive, the supplier&rsquo;s portal — whatever this
              organisation keeps looking up.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <div className="space-y-6">
            {pinned.length > 0 && (
              <section aria-label="Pinned bookmarks" className="space-y-2">
                <h2 className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <PinIcon className="size-3.5" />
                  Pinned
                </h2>
                <SortableContext
                  items={pinned.map((b) => b.id)}
                  strategy={verticalListSortingStrategy}
                >
                  <ul className="space-y-2">
                    {pinned.map((bookmark) => (
                      <Row
                        key={bookmark.id}
                        bookmark={bookmark}
                        canPin={canPin}
                        onSave={save}
                        onDelete={remove}
                        onTogglePin={togglePin}
                      />
                    ))}
                  </ul>
                </SortableContext>
              </section>
            )}

            {rest.length > 0 && (
              <section aria-label="Bookmarks" className="space-y-2">
                {pinned.length > 0 && (
                  <h2 className="text-xs font-medium text-muted-foreground">Everything else</h2>
                )}
                <SortableContext
                  items={rest.map((b) => b.id)}
                  strategy={verticalListSortingStrategy}
                >
                  <ul className="space-y-2">
                    {rest.map((bookmark) => (
                      <Row
                        key={bookmark.id}
                        bookmark={bookmark}
                        canPin={canPin}
                        onSave={save}
                        onDelete={remove}
                        onTogglePin={togglePin}
                      />
                    ))}
                  </ul>
                </SortableContext>
              </section>
            )}
          </div>
        </DndContext>
      )}

      <AddBookmarkDialog
        open={adding}
        onOpenChange={setAdding}
        orgId={org.id}
        onAdded={(bookmark) => setBookmarks((rows) => (rows ? [...rows, bookmark] : [bookmark]))}
      />
    </>
  );
}

function Row({
  bookmark,
  canPin,
  onSave,
  onDelete,
  onTogglePin,
}: {
  bookmark: Bookmark;
  canPin: boolean;
  onSave: (id: string, fields: { url?: string; description?: string }) => Promise<void>;
  onDelete: (bookmark: Bookmark) => void;
  onTogglePin: (bookmark: Bookmark) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: bookmark.id,
  });
  const [editing, setEditing] = useState(false);
  const label = labelOf(bookmark);

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(isDragging && "opacity-40")}
    >
      <Card>
        <CardContent className="flex items-center gap-2 p-3">
          <button
            type="button"
            // Only the grip carries dnd-kit's listeners, so following a link
            // and moving a row never fight over the same click — the same
            // split the Planner's own cards use.
            // "Move X", and the delete button beside it says "Delete X",
            // not "Remove X" — Playwright's `getByRole` name matching is
            // case-insensitive *substring* by default, and "Remove X"
            // contains "move X", so the two labels resolved to the same
            // locator and every drag test failed on strict mode. Same
            // family as the "Priority: Normal" trap CLAUDE.md already
            // records, and cheaper to fix in the copy than in every test.
            aria-label={`Move ${label}`}
            className="shrink-0 cursor-grab touch-none text-muted-foreground hover:text-foreground active:cursor-grabbing"
            {...attributes}
            {...listeners}
          >
            <GripVerticalIcon className="size-4" />
          </button>

          {editing ? (
            <EditFields
              bookmark={bookmark}
              onCancel={() => setEditing(false)}
              onSave={async (fields) => {
                setEditing(false);
                await onSave(bookmark.id, fields);
              }}
            />
          ) : (
            <div className="min-w-0 flex-1">
              <a
                href={bookmark.url}
                target="_blank"
                rel="noreferrer noopener"
                className="flex items-center gap-1 truncate text-sm font-medium hover:underline"
              >
                <span className="truncate">{label}</span>
                <ExternalLinkIcon className="size-3 shrink-0 text-muted-foreground" />
              </a>
              <p className="truncate font-mono text-xs text-muted-foreground">
                {bookmark.url}
                {bookmark.added_by && (
                  <span className="hidden sm:inline">
                    {" · added by "}
                    {bookmark.added_by.display_name || bookmark.added_by.email}
                  </span>
                )}
              </p>
            </div>
          )}

          {!editing && (
            <div className="flex shrink-0 items-center gap-1">
              {/* Absent rather than disabled for anyone who can't — the same
                  "don't show a control that 403s" rule as `can_close`. A
                  non-owner still sees *which* rows are pinned: they sit
                  under the Pinned heading. */}
              {canPin && (
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`${bookmark.pinned ? "Unpin" : "Pin"} ${label}`}
                  onClick={() => onTogglePin(bookmark)}
                >
                  {bookmark.pinned ? <PinOffIcon /> : <PinIcon />}
                </Button>
              )}
              {bookmark.can_edit && (
                <>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Edit ${label}`}
                    onClick={() => setEditing(true)}
                  >
                    <PencilIcon />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Delete ${label}`}
                    onClick={() => onDelete(bookmark)}
                  >
                    <Trash2Icon />
                  </Button>
                </>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </li>
  );
}

/**
 * Edited in place rather than in a dialog: two short fields don't earn a
 * modal, and the row is where you are already looking — the identical call
 * the reminders list makes for its own inline editor.
 *
 * Both fields reseed from the bookmark every time the editor opens, which is
 * what `key` on the parent's `editing` state can't do for us: without it a
 * second edit of the same row hands back whatever was typed and abandoned
 * the first time.
 */
function EditFields({
  bookmark,
  onSave,
  onCancel,
}: {
  bookmark: Bookmark;
  onSave: (fields: { url: string; description: string }) => Promise<void>;
  onCancel: () => void;
}) {
  const [url, setUrl] = useState(bookmark.url);
  const [description, setDescription] = useState(bookmark.description);

  const commit = () => {
    if (!url.trim()) return;
    void onSave({ url: url.trim(), description: description.trim() });
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row">
      <Input
        autoFocus
        aria-label={`Description of ${labelOf(bookmark)}`}
        value={description}
        placeholder="What it's for"
        onChange={(e) => setDescription(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") onCancel();
        }}
      />
      <Input
        aria-label={`URL of ${labelOf(bookmark)}`}
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        className="font-mono text-xs"
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") onCancel();
        }}
      />
      <div className="flex shrink-0 gap-1">
        <Button size="sm" onClick={commit}>
          Save
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function AddBookmarkDialog({
  open,
  onOpenChange,
  orgId,
  onAdded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgId: string;
  onAdded: (bookmark: Bookmark) => void;
}) {
  const toast = useToastManager();
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setUrl("");
    setDescription("");
  };

  const submit = async () => {
    if (!url.trim() || busy) return;
    setBusy(true);
    try {
      const bookmark = await api<Bookmark>(`/organisations/${orgId}/bookmarks`, {
        method: "POST",
        body: JSON.stringify({ url: url.trim(), description: description.trim() }),
      });
      reset();
      onOpenChange(false);
      onAdded(bookmark);
      toast.add({ title: "Bookmark added" });
    } catch (err) {
      toast.add({ title: "Couldn't add that", description: errorDetail(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a bookmark</DialogTitle>
          <DialogDescription>
            Everyone in this organisation will see it. It goes to the end of the list; drag it
            wherever it belongs.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="bookmark-url">Link</Label>
            <Input
              id="bookmark-url"
              autoFocus
              value={url}
              placeholder="example.com/handbook"
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="bookmark-description">Description</Label>
            <Input
              id="bookmark-description"
              value={description}
              placeholder="What it's for"
              onChange={(e) => setDescription(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
            />
          </div>
        </div>
        <DialogFooter>
          <DialogClose render={<Button variant="ghost">Cancel</Button>} />
          <Button onClick={submit} disabled={!url.trim() || busy}>
            Add bookmark
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
