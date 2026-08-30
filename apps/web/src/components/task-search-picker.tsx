import { Popover as PopoverPrimitive } from "@base-ui/react/popover";
import { CircleDotIcon, PlusIcon, SearchIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "@/api";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import type { SearchHit } from "@/lib/types";

/**
 * Pick one task, out of every task in the organisation, to link as a
 * dependency.
 *
 * Deliberately not `EntityPicker`: that component filters an already-fully-
 * fetched `items` array client-side, which is right for people, projects and
 * tags — small closed sets — but wrong here, since "every task in the
 * organisation" can be thousands of rows nobody should hold in the browser
 * at once. This calls the existing `GET /organisations/{id}/search` endpoint
 * per keystroke instead — already access-scoped and fuzzy, no new backend
 * search path — and reuses `search-palette.tsx`'s debounced, sequence-
 * checked, abortable request shape for the same reason that component
 * documents: out-of-order answers and mid-flight "nothing found" are both
 * real bugs on a real connection, invisible on localhost.
 *
 * Still built on `EntityPicker`'s `Popover` shell, though — a field inside a
 * `Card` needs the identical portal-and-positioner fix (`Card` clips an
 * `absolute` child unconditionally), and Base UI's own dismissal is what
 * keeps Escape closing this list rather than a dialog behind it.
 */
const DEBOUNCE_MS = 150;

export function TaskSearchPicker({
  orgId,
  excludeTaskIds,
  onSelect,
  disabled,
  placeholder = "Link a task…",
}: {
  orgId: string;
  /** The current task, and anything already listed — kept out of results so
   *  you can't pick a duplicate or a self-reference from the search itself. */
  excludeTaskIds: Set<string>;
  onSelect: (hit: SearchHit) => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [settled, setSettled] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const seq = useRef(0);
  const inflight = useRef<AbortController | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      inflight.current?.abort();
      setHits([]);
      setLoading(false);
      setSettled(false);
      return;
    }
    setLoading(true);
    const mine = ++seq.current;
    const timer = setTimeout(async () => {
      inflight.current?.abort();
      const controller = new AbortController();
      inflight.current = controller;
      try {
        const data = await api<{ hits: SearchHit[] }>(
          `/organisations/${orgId}/search?q=${encodeURIComponent(q)}&limit=8`,
          { signal: controller.signal },
        );
        if (mine !== seq.current) return;
        setHits(data.hits.filter((h) => h.kind === "task" && !excludeTaskIds.has(h.id)));
        setActive(0);
        setSettled(true);
      } catch {
        if (mine === seq.current) setSettled(true);
      } finally {
        if (mine === seq.current) setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // `excludeTaskIds` deliberately isn't a dependency: the caller may pass a
    // freshly-built Set on every render, and re-running the search because
    // of that (rather than because the query changed) would refetch on every
    // keystroke of an unrelated field.
  }, [query, orgId]);

  const choose = (hit: SearchHit) => {
    onSelect(hit);
    setOpen(false);
    setQuery("");
    setHits([]);
    setSettled(false);
  };

  return (
    <PopoverPrimitive.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setQuery("");
          setHits([]);
          setSettled(false);
          inflight.current?.abort();
        }
      }}
    >
      <PopoverPrimitive.Trigger
        render={<Button type="button" variant="outline" size="sm" disabled={disabled} />}
      >
        <PlusIcon className="size-4" />
        {placeholder}
      </PopoverPrimitive.Trigger>

      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Positioner
          className="z-50 outline-none"
          side="bottom"
          align="start"
          sideOffset={4}
        >
          <PopoverPrimitive.Popup
            initialFocus={input}
            className="flex w-80 max-h-(--available-height) flex-col overflow-hidden rounded-lg border bg-popover shadow-md"
          >
            <div className="flex shrink-0 items-center gap-2 border-b px-3">
              <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
              <input
                ref={input}
                value={query}
                aria-label="Search tasks"
                placeholder="Type a title…"
                className="h-9 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    setActive((i) => (hits.length ? (i + 1) % hits.length : 0));
                  } else if (event.key === "ArrowUp") {
                    event.preventDefault();
                    setActive((i) => (hits.length ? (i - 1 + hits.length) % hits.length : 0));
                  } else if (event.key === "Enter" && hits[active]) {
                    event.preventDefault();
                    choose(hits[active]);
                  }
                }}
              />
              {loading && <Spinner className="size-3.5 shrink-0" />}
            </div>

            <div role="listbox" className="min-h-0 max-h-64 flex-1 overflow-y-auto p-1">
              {hits.map((hit, i) => (
                <button
                  key={hit.id}
                  type="button"
                  role="option"
                  aria-selected={i === active}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => choose(hit)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
                    i === active && "bg-accent",
                  )}
                >
                  <CircleDotIcon className="size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className={cn("block truncate", hit.inactive && "line-through")}>
                      {hit.title}
                    </span>
                    {hit.context && (
                      <span className="block truncate text-xs text-muted-foreground">
                        {hit.context}
                      </span>
                    )}
                  </span>
                </button>
              ))}
              {!query.trim() && (
                <p className="px-2 py-4 text-center text-sm text-muted-foreground">
                  Type to find a task.
                </p>
              )}
              {query.trim() && settled && hits.length === 0 && (
                <p className="px-2 py-4 text-center text-sm text-muted-foreground">
                  Nothing matches &ldquo;{query.trim()}&rdquo;.
                </p>
              )}
            </div>
          </PopoverPrimitive.Popup>
        </PopoverPrimitive.Positioner>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
