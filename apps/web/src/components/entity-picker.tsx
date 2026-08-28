import { Popover as PopoverPrimitive } from "@base-ui/react/popover";
import { CheckIcon, ChevronsUpDownIcon, SearchIcon, XIcon } from "lucide-react";
import { useMemo, useRef, useState } from "react";

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
 * Built on Base UI's `Popover` (non-modal) rather than a hand-rolled
 * `absolute` div, and that isn't a style choice — a plain absolutely
 * positioned child is clipped by any ancestor with `overflow-hidden`, which
 * `Card` sets unconditionally (for rounding cover images to its corners).
 * Every picker that lives inside a `Card` — Priority, Project, the lot —
 * had its list silently cut off the moment the card wasn't tall enough to
 * contain it. `Popover.Portal` renders outside that ancestor chain entirely,
 * and `Popover.Positioner` is what gives it `--anchor-width` (matching the
 * trigger) and `--available-height` (flipping above the trigger when there
 * isn't room below) for free — the same primitives `DropdownMenuContent`
 * already uses. It also means Base UI, not a hand-rolled document listener,
 * owns dismissal — which is what keeps Escape closing only this list and not
 * a dialog behind it (`useDismiss`'s nested-floating-tree awareness), and
 * what keeps a click *inside* the portaled list from reading as "outside"
 * and closing it before the click is registered.
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

  const choose = (item: PickerItem) => {
    onChange(item.value || null);
    setOpen(false);
  };

  return (
    <PopoverPrimitive.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setQuery("");
          setActive(0);
        }
      }}
    >
      <PopoverPrimitive.Trigger
        render={
          <Button
            id={id}
            type="button"
            variant="outline"
            disabled={disabled}
            aria-label={ariaLabel}
            className="w-full justify-between font-normal"
          />
        }
      >
        <span className={cn("flex min-w-0 items-center gap-2", !selected && "text-muted-foreground")}>
          {selected?.icon}
          <span className="truncate">{selected?.label ?? placeholder}</span>
        </span>
        <ChevronsUpDownIcon className="size-4 shrink-0 opacity-60" />
      </PopoverPrimitive.Trigger>

      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Positioner
          className="z-50 outline-none"
          side="bottom"
          align="start"
          sideOffset={4}
        >
          <PopoverPrimitive.Popup
            // Focus the filter input, not "the first tabbable element" —
            // they're the same element today, but this is the actual
            // requirement, not an accident of DOM order.
            initialFocus={input}
            className="flex w-(--anchor-width) max-h-(--available-height) flex-col overflow-hidden rounded-lg border bg-popover shadow-md"
          >
            <div className="flex shrink-0 items-center gap-2 border-b px-3">
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

            <div role="listbox" className="min-h-0 max-h-64 flex-1 overflow-y-auto p-1">
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
          </PopoverPrimitive.Popup>
        </PopoverPrimitive.Positioner>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
