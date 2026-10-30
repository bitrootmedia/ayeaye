import { SearchIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { personName, type Person } from "@/lib/types";

/**
 * Choose several people at once — a group's members.
 *
 * Not `EntityPicker`, which is one value by design: a group of six picked one
 * at a time through a popover that closes after each choice is six round
 * trips through the same list. This is the list itself, in flow, with a
 * filter above it — it lives in a dialog, so there is no card to clip it.
 */
export function PeoplePicker({
  people,
  selected,
  onChange,
  exclude = [],
}: {
  people: Person[];
  selected: string[];
  onChange: (ids: string[]) => void;
  /** Already in — yourself, or a group's current members. Not offered,
   *  rather than offered and doing nothing. */
  exclude?: string[];
}) {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return people
      .filter((p) => !exclude.includes(p.id))
      .filter(
        (p) =>
          !q ||
          (p.display_name ?? "").toLowerCase().includes(q) ||
          (p.email ?? "").toLowerCase().includes(q),
      )
      .sort((a, b) => personName(a).localeCompare(personName(b)));
  }, [people, exclude, query]);

  const toggle = (id: string) =>
    onChange(selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id]);

  return (
    <div className="space-y-2">
      <div className="relative">
        <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Find a person…"
          aria-label="Find a person"
          className="pl-8"
        />
      </div>
      <ul className="max-h-64 overflow-y-auto rounded-md border">
        {shown.length === 0 ? (
          <li className="px-3 py-2 text-sm text-muted-foreground">Nobody matches.</li>
        ) : (
          shown.map((p) => (
            <li key={p.id}>
              <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-accent/50">
                <Checkbox
                  checked={selected.includes(p.id)}
                  onCheckedChange={() => toggle(p.id)}
                  aria-label={personName(p)}
                />
                <span className="truncate">{personName(p)}</span>
                {p.display_name && p.email && (
                  <span className="ml-auto truncate font-mono text-xs text-muted-foreground">
                    {p.email}
                  </span>
                )}
              </label>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
