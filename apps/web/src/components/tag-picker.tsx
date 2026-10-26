import { ArchiveIcon, PlusIcon, TagIcon, XIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ApiError, api } from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToastManager } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import type { Tag } from "@/lib/types";

/**
 * Tags on a task, an article or a fact: the chips, and the thing that adds one.
 *
 * **`basePath`, not a `taskId`** — the generalisation `AccessPanel` and
 * `FilesPanel` already went through, for the same reason: a second real
 * caller. All three resources answer `POST {basePath}/tags` with a name and
 * `DELETE {basePath}/tags/{id}`. `noun` keeps the one sentence that names
 * the resource honest — see `FilesPanel`'s own note on why a shared
 * component must not swallow a caller's word.
 *
 * **Not `EntityPicker`.** Every other picker chooses one of a fixed set; this
 * one has to offer "create «what you typed»" when nothing matches, because a
 * vocabulary that can only be extended from a settings screen is a vocabulary
 * nobody extends. The API is get-or-create by name, so typing an existing tag
 * in a different case lands on the existing one rather than making a twin.
 */
export function TagStrip({
  orgId,
  basePath,
  tags,
  editable,
  onChanged,
  noun = "task",
}: {
  orgId: string;
  /** e.g. `/organisations/{org}/tasks/{task}` or `/organisations/{org}/kb/facts/{fact}`. */
  basePath: string;
  tags: Tag[];
  editable: boolean;
  onChanged: () => Promise<void> | void;
  noun?: string;
}) {
  const toast = useToastManager();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [all, setAll] = useState<Tag[]>([]);
  // **Nothing is offered until the vocabulary has arrived.** Otherwise the
  // list is briefly empty and the panel offers to *create* a tag that already
  // exists — the API's get-or-create saves the data, but the screen has still
  // told you something false about your own organisation.
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setLoading(true);
    void api<Tag[]>(`/organisations/${orgId}/tags`)
      .then(setAll)
      .catch(() => setAll([]))
      .finally(() => setLoading(false));
    const id = requestAnimationFrame(() => input.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [open, orgId]);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // Capture, and it stops here — this lives inside dialogs too. Same
      // reasoning as EntityPicker.
      event.stopPropagation();
      setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  const q = query.trim();
  const mine = new Set(tags.map((t) => t.id));
  const matches = all
    .filter((t) => !mine.has(t.id))
    .filter((t) => !q || t.name.toLowerCase().includes(q.toLowerCase()));
  // Only when nothing in the vocabulary already says it, case-insensitively.
  const canCreate =
    !loading && q.length > 0 && !all.some((t) => t.name.toLowerCase() === q.toLowerCase());

  const add = async (name: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await api(`${basePath}/tags`, {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      setOpen(false);
      await onChanged();
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "Couldn't add that tag", description: detail });
    } finally {
      setBusy(false);
    }
  };

  const remove = async (tag: Tag) => {
    try {
      await api(`${basePath}/tags/${tag.id}`, { method: "DELETE" });
      await onChanged();
    } catch {
      toast.add({ title: "Couldn't remove that tag" });
    }
  };

  return (
    <div ref={root} className="relative flex flex-wrap items-center gap-1.5">
      {tags.map((tag) => (
        <TagChip key={tag.id} tag={tag} onRemove={editable ? () => remove(tag) : undefined} />
      ))}

      {editable && (
        <Button
          size="xs"
          variant="ghost"
          aria-label="Add a tag"
          className="text-muted-foreground"
          onClick={() => setOpen((v) => !v)}
        >
          <PlusIcon />
          Tag
        </Button>
      )}

      {open && (
        <div className="absolute top-full left-0 z-50 mt-1 w-64 overflow-hidden rounded-lg border bg-popover shadow-md">
          <input
            ref={input}
            value={query}
            aria-label="Find or create a tag"
            placeholder="Find or create a tag…"
            className="h-9 w-full border-b bg-transparent px-3 text-sm outline-none placeholder:text-muted-foreground"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              e.preventDefault();
              // Enter takes the first match, or creates what you typed. Never
              // both — the list is above the create row, so the eye has
              // already answered which one is meant.
              if (matches.length) void add(matches[0].name);
              else if (canCreate) void add(q);
            }}
          />
          <div className="max-h-56 overflow-y-auto p-1">
            {matches.map((tag) => (
              <button
                key={tag.id}
                type="button"
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent"
                onClick={() => add(tag.name)}
              >
                <TagIcon className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate">{tag.name}</span>
                {tag.off_board && <OffBoardMark />}
              </button>
            ))}
            {canCreate && (
              <button
                type="button"
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent"
                onClick={() => add(q)}
              >
                <PlusIcon className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate">
                  Create &ldquo;{q}&rdquo;
                </span>
              </button>
            )}
            {loading && (
              <p className="px-2 py-4 text-center text-sm text-muted-foreground">Loading…</p>
            )}
            {!loading && !matches.length && !canCreate && (
              <p className="px-2 py-4 text-center text-sm text-muted-foreground">
                {q ? `Already on this ${noun}.` : "No tags yet — type to make one."}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** A tag, everywhere it appears. No colour: status owns the only scale. */
export function TagChip({
  tag,
  onRemove,
  className,
}: {
  tag: Tag;
  onRemove?: () => void;
  className?: string;
}) {
  return (
    <Badge variant="outline" className={cn("gap-1 font-normal", className)}>
      {tag.off_board ? (
        <OffBoardMark />
      ) : (
        <TagIcon className="size-3 shrink-0 text-muted-foreground" />
      )}
      {tag.name}
      {onRemove && (
        <button
          type="button"
          aria-label={`Remove tag ${tag.name}`}
          className="-mr-0.5 rounded-sm text-muted-foreground hover:text-foreground"
          onClick={onRemove}
        >
          <XIcon className="size-3" />
        </button>
      )}
    </Badge>
  );
}

/** Shape, not colour — the same discipline as priority. */
function OffBoardMark() {
  return (
    <ArchiveIcon
      className="size-3 shrink-0 text-muted-foreground"
      aria-label="Kept off the board"
    />
  );
}
