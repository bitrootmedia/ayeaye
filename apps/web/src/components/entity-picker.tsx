import { CheckIcon, ChevronsUpDownIcon, SearchIcon, XIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Choosing one thing from a list that might be long.
 *
 * A plain `<select>` is fine for six statuses and useless for eighty projects
 * or two hundred people: you cannot type, and the browser's own type-ahead
 * only matches from the start of the label. This opens a list with the filter
 * already focused, so choosing is always "type three letters, Enter".
 *
 * Deliberately **not** a modal. Field editing should keep its context on
 * screen — you are looking at a task, and which task it is matters while you
 * pick. ⌘K's palette is a different job and is modal for good reason.
 *
 * Keyboard: type to filter, ↑↓ to move, Enter to choose, Escape to close.
 */
export type PickerItem = {
  value: string;
  label: string;
  /** Second line — an email, a project group. Searched as well as shown. */
  hint?: string;
  icon?: React.ReactNode;
};

export function EntityPicker({
  items,
  value,
  onChange,
  placeholder = "Choose…",
  searchPlaceholder = "Type to filter…",
  emptyLabel,
  disabled,
  id,
  ariaLabel,
}: {
  items: PickerItem[];
  value: string | null;
  onChange: (value: string | null) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  /** When set, an explicit "none" row — clearing is a choice, not an absence. */
  emptyLabel?: string;
  disabled?: boolean;
  id?: string;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  const selected = items.find((item) => item.value === value) ?? null;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = q
      ? items.filter(
          (item) =>
            item.label.toLowerCase().includes(q) || item.hint?.toLowerCase().includes(q),
        )
      : items;
    return emptyLabel && !q ? [{ value: "", label: emptyLabel }, ...rows] : rows;
  }, [items, query, emptyLabel]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    // Focus after paint, or the browser hands focus back to the trigger.
    const id = requestAnimationFrame(() => input.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [open]);

  // Click-away and Escape, bound only while open.
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // **Capture phase, and it stops here.** This picker is used inside
      // dialogs, which close on Escape themselves — without this, dismissing
      // the list also throws away the half-typed task behind it. Escape
      // closes the innermost thing, which is this.
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

  const choose = (item: PickerItem) => {
    onChange(item.value || null);
    setOpen(false);
  };

  return (
    <div ref={root} className="relative">
      <Button
        id={id}
        type="button"
        variant="outline"
        disabled={disabled}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="w-full justify-between font-normal"
        onClick={() => setOpen((v) => !v)}
      >
        <span className={cn("flex min-w-0 items-center gap-2", !selected && "text-muted-foreground")}>
          {selected?.icon}
          <span className="truncate">{selected?.label ?? placeholder}</span>
        </span>
        <ChevronsUpDownIcon className="size-4 shrink-0 opacity-60" />
      </Button>

      {open && (
        <div className="absolute z-50 mt-1 w-full overflow-hidden rounded-lg border bg-popover shadow-md">
          <div className="flex items-center gap-2 border-b px-3">
            <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
            <input
              ref={input}
              value={query}
              aria-label={searchPlaceholder}
              placeholder={searchPlaceholder}
              className="h-9 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              onChange={(e) => {
                setQuery(e.target.value);
                setActive(0);
              }}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  setActive((i) => (filtered.length ? (i + 1) % filtered.length : 0));
                } else if (event.key === "ArrowUp") {
                  event.preventDefault();
                  setActive((i) =>
                    filtered.length ? (i - 1 + filtered.length) % filtered.length : 0,
                  );
                } else if (event.key === "Enter" && filtered[active]) {
                  event.preventDefault();
                  choose(filtered[active]);
                }
              }}
            />
            {query && (
              <button
                type="button"
                aria-label="Clear filter"
                className="rounded-sm p-0.5 hover:bg-muted"
                onClick={() => {
                  setQuery("");
                  input.current?.focus();
                }}
              >
                <XIcon className="size-3.5" />
              </button>
            )}
          </div>

          <div role="listbox" className="max-h-64 overflow-y-auto p-1">
            {filtered.map((item, i) => (
              <button
                key={item.value || "__none__"}
                type="button"
                role="option"
                aria-selected={item.value === (value ?? "")}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(item)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
                  i === active && "bg-accent",
                )}
              >
                {item.icon}
                <span className="min-w-0 flex-1">
                  <span className={cn("block truncate", !item.value && "text-muted-foreground")}>
                    {item.label}
                  </span>
                  {item.hint && (
                    <span className="block truncate font-mono text-xs text-muted-foreground">
                      {item.hint}
                    </span>
                  )}
                </span>
                {item.value === (value ?? "") && <CheckIcon className="size-4 shrink-0" />}
              </button>
            ))}
            {filtered.length === 0 && (
              <p className="px-2 py-4 text-center text-sm text-muted-foreground">
                Nothing matches &ldquo;{query.trim()}&rdquo;.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
