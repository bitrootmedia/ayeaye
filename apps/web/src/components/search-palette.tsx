import { CircleDotIcon, FolderKanbanIcon, NotebookPenIcon, SearchIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "@/api";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import type { SearchHit } from "@/lib/types";

/**
 * Search, from anywhere. ⌘K / Ctrl+K, or the box in the header.
 *
 * Three things make it feel instant, and all three are about *not* doing
 * something:
 *
 * 1. **Requests are aborted, and answers are sequence-checked.** Typing
 *    "antifoul" fires eight requests; they can come back in any order. Without
 *    a guard, a slow answer for "ant" lands after the fast one for "antifoul"
 *    and overwrites the right results with stale ones. That bug is invisible
 *    on a fast local connection and constant on a real one.
 * 2. **Old results stay on screen while new ones load.** Clearing the list on
 *    every keystroke makes the panel strobe; keeping it and dimming it reads
 *    as fast even when the network isn't.
 * 3. **"Nothing found" only appears after a settled search.** Showing it
 *    mid-flight tells people their thing doesn't exist a beat before it
 *    appears.
 *
 * Everything it returns is already inside the access model — the API resolves
 * visibility in the same statement as the text match, so there is no filtering
 * to do here and no chance of showing a title the person may not see.
 */

const DEBOUNCE_MS = 120;
const KIND_ICON = {
  task: CircleDotIcon,
  project: FolderKanbanIcon,
  // A private note. The hit IS a note but the link is to the task — you
  // search your notes to get back to the work, not to read them here.
  note: NotebookPenIcon,
} as const;

export function SearchPalette({
  orgId,
  open,
  onOpenChange,
}: {
  orgId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [settled, setSettled] = useState(false);
  const [active, setActive] = useState(0);

  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  // Monotonic: only the newest request may write to state.
  const seq = useRef(0);
  const inflight = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    setQuery("");
    setHits([]);
    setActive(0);
    setSettled(false);
    inflight.current?.abort();
  }, []);

  useEffect(() => {
    if (!open) reset();
  }, [open, reset]);

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
          `/organisations/${orgId}/search?q=${encodeURIComponent(q)}&limit=6`,
          { signal: controller.signal },
        );
        // The guard. An out-of-order answer for an older query is dropped.
        if (mine !== seq.current) return;
        setHits(data.hits);
        setActive(0);
        setSettled(true);
      } catch {
        // An abort is the normal case here, not a failure.
        if (mine === seq.current) setSettled(true);
      } finally {
        if (mine === seq.current) setLoading(false);
      }
    }, DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [query, orgId]);

  const go = useCallback(
    (hit: SearchHit) => {
      onOpenChange(false);
      navigate(
        hit.kind === "project"
          ? `/orgs/${orgId}/projects/${hit.id}`
          : // Both tasks and note hits carry the task's id.
            `/orgs/${orgId}/tasks/${hit.id}`,
      );
    },
    [navigate, onOpenChange, orgId],
  );

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => (hits.length ? (i + 1) % hits.length : 0));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => (hits.length ? (i - 1 + hits.length) % hits.length : 0));
    } else if (event.key === "Enter" && hits[active]) {
      event.preventDefault();
      go(hits[active]);
    }
  };

  // Keep the highlighted row in view when arrowing past the fold.
  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>(`[data-index="${active}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="top-24 max-w-xl translate-y-0 gap-0 overflow-hidden p-0"
        showCloseButton={false}
      >
        <DialogTitle className="sr-only">Search</DialogTitle>

        <div className="flex items-center gap-3 border-b px-4">
          {loading ? (
            <Spinner className="size-4 shrink-0 text-muted-foreground" />
          ) : (
            <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
          )}
          <input
            ref={inputRef}
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search tasks and projects…"
            aria-label="Search"
            className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
        </div>

        <div ref={listRef} className="max-h-80 overflow-y-auto p-1.5">
          {hits.map((hit, i) => {
            const Icon = KIND_ICON[hit.kind as keyof typeof KIND_ICON] ?? CircleDotIcon;
            return (
              <button
                key={`${hit.kind}-${hit.id}`}
                type="button"
                data-index={i}
                onMouseEnter={() => setActive(i)}
                onClick={() => go(hit)}
                className={cn(
                  "flex w-full items-start gap-3 rounded-md px-2.5 py-2 text-left",
                  i === active && "bg-accent",
                )}
              >
                <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span
                      className={cn(
                        "truncate text-sm",
                        hit.inactive && "text-muted-foreground line-through",
                      )}
                    >
                      {hit.title}
                    </span>
                    {hit.context && (
                      <span className="shrink-0 truncate text-xs text-muted-foreground">
                        {hit.context}
                      </span>
                    )}
                  </span>
                  {hit.subtitle && (
                    <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                      {hit.subtitle}
                    </span>
                  )}
                </span>
              </button>
            );
          })}

          {/* Only once a search has actually finished — see the note above. */}
          {settled && !loading && query.trim() && hits.length === 0 && (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">
              Nothing matches &ldquo;{query.trim()}&rdquo;.
              <br />
              <span className="text-xs">
                Search only covers what you have access to.
              </span>
            </p>
          )}

          {!query.trim() && (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">
              Start typing to search tasks and projects.
            </p>
          )}
        </div>

        <div className="flex items-center justify-between border-t px-4 py-2 text-xs text-muted-foreground">
          <span>
            <Key>↑</Key> <Key>↓</Key> to move · <Key>↵</Key> to open
          </span>
          <span>
            <Key>esc</Key> to close
          </span>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Key({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border bg-muted px-1 font-mono text-[0.65rem] text-muted-foreground">
      {children}
    </kbd>
  );
}

/**
 * The header affordance.
 *
 * A visible box, not just a shortcut: ⌘K is invisible to anyone who hasn't
 * been told about it, and search being discoverable is the difference between
 * a feature and a secret.
 */
export function SearchTrigger({ onClick }: { onClick: () => void }) {
  const [mac, setMac] = useState(true);
  useEffect(() => {
    setMac(/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent));
  }, []);

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Search"
      className="flex h-9 items-center gap-2 rounded-md border bg-background px-3 text-sm text-muted-foreground transition-colors hover:bg-accent md:w-64"
    >
      <SearchIcon className="size-4 shrink-0" />
      <span className="hidden md:inline">Search…</span>
      <Key>{mac ? "⌘" : "Ctrl"}K</Key>
    </button>
  );
}

/** Bind ⌘K / Ctrl+K globally. */
export function useSearchHotkey(onOpen: () => void) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        onOpen();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onOpen]);
}
