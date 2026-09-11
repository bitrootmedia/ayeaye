import { PencilIcon, PlusIcon, ScrollTextIcon, SearchIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useOutletContext, useParams, useSearchParams } from "react-router-dom";

import { ApiError, api, apiWithHeaders } from "@/api";
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
import { Textarea } from "@/components/ui/textarea";
import { useToastManager } from "@/components/ui/toast";
import { isoDate } from "@/lib/format";
import { personName, type ChangelogEntry } from "@/lib/types";

/** Rows per page, and how much "Show more" adds. Half the task list's own
 *  100: a row here is prose rather than a table line, so fifty of them is
 *  already a long scroll. */
const PAGE = 50;

const errorDetail = (err: unknown) =>
  err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";

/** Consecutive entries sharing a date, so the date is stated once per day
 *  rather than repeated down the column. The server already orders by date
 *  descending, so "consecutive" and "same day" are the same grouping — no
 *  sorting happens here, and none should: the order is the server's. */
function byDate(entries: ChangelogEntry[]): { date: string; entries: ChangelogEntry[] }[] {
  const groups: { date: string; entries: ChangelogEntry[] }[] = [];
  for (const entry of entries) {
    const last = groups[groups.length - 1];
    if (last && last.date === entry.happened_on) last.entries.push(entry);
    else groups.push({ date: entry.happened_on, entries: [entry] });
  }
  return groups;
}

/**
 * The organisation's changelog: a dated log of things that happened.
 *
 * "BingAds version lift, the 3rd." Three fields and no more — the date, what
 * happened, and who wrote it down.
 *
 * **Shared, like the bookmark shelf and unlike the notepad**: every member
 * reads the same log and any member can add to it, because a log only an
 * admin may write to is one that stays empty — and an incomplete history is
 * worse than none, since people believe it. Correcting or removing an entry
 * is whoever recorded it, or an org admin (`services/changelog.py`), resolved
 * server-side into `can_edit` so the controls are absent rather than present
 * and refusing.
 *
 * **Nothing here reorders, unlike bookmarks.** A shelf of links has no
 * inherent order so one is worth storing; a log's order is its dates, and
 * dragging an entry above one that happened after it would let the list lie
 * about the sequence — which is the one thing a changelog is for.
 *
 * **Paged**, also unlike bookmarks: a shelf is curated and stops growing, a
 * log only ever gets longer. `X-Total-Count` is what makes "Showing 50 of
 * 312" honest rather than a guess.
 */
export default function Changelog() {
  const { orgId } = useParams<{ orgId: string }>();
  const { organisations } = useOutletContext<Shell>();
  const toast = useToastManager();
  const org = organisations.find((o) => o.id === orgId) ?? null;

  // The filter lives in the URL, same reasoning as every other view and
  // filter in the product: a log somebody narrowed is one they can send a
  // colleague — and it is also where ⌘K lands a changelog hit, carrying the
  // query it matched on.
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [draft, setDraft] = useState(q);

  const [entries, setEntries] = useState<ChangelogEntry[] | null>(null);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(PAGE);
  const [adding, setAdding] = useState(false);
  // A counter that keys the dialog, so every open mounts a *fresh instance*
  // — the same "a different thing is a different component" idiom `Keyed` in
  // main.tsx uses for detail routes. The alternative is an effect that
  // clears the fields when `open` flips, and the difference is worth the one
  // extra piece of state: the date comes from `useState`'s initialiser at
  // mount, so it is today every time you open it without anything ever
  // *writing over* a field somebody may already be typing into.
  const [openSeq, setOpenSeq] = useState(0);

  const load = useCallback(async () => {
    if (!orgId) return;
    try {
      const res = await apiWithHeaders<ChangelogEntry[]>(
        `/organisations/${orgId}/changelog?limit=${limit}&q=${encodeURIComponent(q)}`,
      );
      setEntries(res.data);
      setTotal(Number(res.headers.get("X-Total-Count") ?? res.data.length));
    } catch {
      setEntries([]);
      setTotal(0);
    }
  }, [orgId, limit, q]);

  useEffect(() => {
    void load();
  }, [load]);

  // Arriving from ⌘K (or a shared link) seeds the box from the URL rather
  // than the other way round — otherwise the field is empty while the list
  // beneath it is plainly filtered.
  useEffect(() => {
    setDraft(q);
  }, [q]);

  // Typing narrows the URL, debounced: every keystroke is a round trip
  // otherwise, and `replace` so a filter isn't a dozen back-button steps.
  useEffect(() => {
    if (draft === q) return;
    const timer = setTimeout(() => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (draft.trim()) next.set("q", draft.trim());
          else next.delete("q");
          return next;
        },
        { replace: true },
      );
      // A narrowed list is a different list, so it starts at its own first
      // page rather than inheriting however far the last one was scrolled.
      setLimit(PAGE);
    }, 250);
    return () => clearTimeout(timer);
  }, [draft, q, setParams]);

  const groups = useMemo(() => byDate(entries ?? []), [entries]);

  const save = async (id: string, fields: { description: string; happened_on: string }) => {
    try {
      const updated = await api<ChangelogEntry>(`/organisations/${orgId}/changelog/${id}`, {
        method: "PATCH",
        body: JSON.stringify(fields),
      });
      // Reloaded rather than patched in place when the date moved: a redated
      // entry belongs somewhere else in the order, and where exactly is the
      // server's ordering to state rather than ours to guess.
      const moved = entries?.find((e) => e.id === id)?.happened_on !== updated.happened_on;
      if (moved) await load();
      else setEntries((rows) => rows?.map((e) => (e.id === id ? updated : e)) ?? rows);
      toast.add({ title: "Entry updated" });
    } catch (err) {
      toast.add({ title: "Couldn't save that", description: errorDetail(err) });
    }
  };

  const remove = async (entry: ChangelogEntry) => {
    // Optimistic: the row goes now and comes back on the next load if the
    // request failed — the same call the bookmark shelf makes.
    setEntries((rows) => rows?.filter((e) => e.id !== entry.id) ?? rows);
    setTotal((n) => Math.max(0, n - 1));
    try {
      await api(`/organisations/${orgId}/changelog/${entry.id}`, { method: "DELETE" });
    } catch (err) {
      toast.add({ title: "Couldn't remove that", description: errorDetail(err) });
      await load();
    }
  };

  if (!org) return null;

  return (
    <>
      <PageHeader
        crumbs={[{ label: org.name, to: `/orgs/${org.id}` }, { label: "Changelog" }]}
        title="Changelog"
        description="What happened, and when — a version lift, a config change, anything worth looking up later."
        actions={
          <Button
            onClick={() => {
              setOpenSeq((n) => n + 1);
              setAdding(true);
            }}
          >
            <PlusIcon />
            Add entry
          </Button>
        }
      />

      {/* Absent until there is something to narrow: a filter box over an
          empty log is a control that can only disappoint. Still rendered
          while a filter is active and matching nothing, or there would be no
          way to clear it. */}
      {(q !== "" || (entries !== null && entries.length > 0)) && (
        <div className="relative max-w-sm">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Filter the changelog"
            placeholder="Filter…"
            className="pl-8"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
        </div>
      )}

      {entries === null ? (
        <div className="flex flex-1 items-center justify-center py-12">
          <Spinner />
        </div>
      ) : entries.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <ScrollTextIcon />
            </EmptyMedia>
            <EmptyTitle>{q ? "Nothing matches that" : "Nothing recorded yet"}</EmptyTitle>
            <EmptyDescription>
              {q ? (
                <>Try fewer words, or clear the filter to see the whole log.</>
              ) : (
                <>
                  A version lift, a config change, a supplier switched — whatever this
                  organisation will want the date of later.
                </>
              )}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <>
          <div className="space-y-6">
            {groups.map((group) => (
              <section key={group.date} aria-label={`Changelog for ${group.date}`}>
                {/* The date is data, so it is mono with tabular figures and
                    the dates line up down the column. Stated once per day
                    rather than repeated on every row of it. */}
                <h2 className="mb-2 font-mono text-xs font-medium text-muted-foreground">
                  {group.date}
                </h2>
                <ul className="space-y-2">
                  {group.entries.map((entry) => (
                    <Row key={entry.id} entry={entry} onSave={save} onDelete={remove} />
                  ))}
                </ul>
              </section>
            ))}
          </div>

          <div className="flex items-center justify-between gap-3 pt-2">
            <span className="font-mono text-xs text-muted-foreground">
              {/* Says what the page is a page *of* — the same honesty the
                  task list's own pager keeps. */}
              Showing {entries.length} of {total}
            </span>
            {entries.length < total && (
              <Button variant="outline" size="sm" onClick={() => setLimit((n) => n + PAGE)}>
                Show more
              </Button>
            )}
          </div>
        </>
      )}

      <AddEntryDialog
        key={openSeq}
        open={adding}
        onOpenChange={setAdding}
        orgId={org.id}
        onAdded={load}
      />
    </>
  );
}

function Row({
  entry,
  onSave,
  onDelete,
}: {
  entry: ChangelogEntry;
  onSave: (id: string, fields: { description: string; happened_on: string }) => Promise<void>;
  onDelete: (entry: ChangelogEntry) => void;
}) {
  const [editing, setEditing] = useState(false);
  // Seeded when the editor opens rather than left to `useState`'s initial
  // value, which runs once and would hand back whatever was typed and
  // abandoned the first time — the same stale-local-state trap the reminders
  // list and the task screen both document.
  const [description, setDescription] = useState(entry.description);
  const [when, setWhen] = useState(entry.happened_on);

  // Enough of the description to tell two rows apart in an accessible name
  // without putting a whole paragraph into one. Tests address the Edit and
  // Delete buttons by it, so it has to come from the entry itself rather
  // than from its position in a list that reorders on every edit.
  const label = entry.description.slice(0, 40);

  const startEditing = () => {
    setDescription(entry.description);
    setWhen(entry.happened_on);
    setEditing(true);
  };

  const commit = () => {
    if (!description.trim() || !when) return;
    setEditing(false);
    void onSave(entry.id, { description: description.trim(), happened_on: when });
  };

  if (editing) {
    return (
      <li>
        <Card>
          <CardContent className="space-y-2 p-3">
            <Input
              type="date"
              aria-label={`Date for ${label}`}
              className="w-40"
              value={when}
              onChange={(e) => setWhen(e.target.value)}
            />
            <Textarea
              autoFocus
              aria-label={`Description of ${label}`}
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onKeyDown={(e) => {
                // ⌘/Ctrl+Enter commits; a bare Enter is a new line, because
                // this field is deliberately multi-line.
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) commit();
                if (e.key === "Escape") setEditing(false);
              }}
            />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                Cancel
              </Button>
              <Button size="sm" disabled={!description.trim() || !when} onClick={commit}>
                Save
              </Button>
            </div>
          </CardContent>
        </Card>
      </li>
    );
  }

  return (
    <li>
      <Card>
        <CardContent className="flex items-start gap-2 p-3">
          <div className="min-w-0 flex-1">
            {/* Plain text, never `dangerouslySetInnerHTML` — which is why
                there is nothing to sanitise here, the same safe-by-
                construction position Sparks holds. `pre-wrap` so a
                paragraph somebody typed keeps its line breaks. */}
            <p className="text-sm whitespace-pre-wrap">{entry.description}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {entry.added_by
                ? `Added by ${personName(entry.added_by)}`
                : "Added by a former member"}
              {entry.updated_at !== entry.created_at && " · edited"}
            </p>
          </div>
          {entry.can_edit && (
            <div className="flex shrink-0 items-center gap-1">
              <Button size="sm" variant="ghost" aria-label={`Edit ${label}`} onClick={startEditing}>
                <PencilIcon />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                // "Delete", not "Remove": Playwright's role-name matching is
                // case-insensitive *substring*, and "Remove X" contains
                // "move X" — the trap the bookmark shelf's own copy
                // documents.
                aria-label={`Delete ${label}`}
                onClick={() => onDelete(entry)}
              >
                <Trash2Icon />
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </li>
  );
}

function AddEntryDialog({
  open,
  onOpenChange,
  orgId,
  onAdded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgId: string;
  onAdded: () => Promise<void>;
}) {
  const toast = useToastManager();
  const [description, setDescription] = useState("");
  // Today, resolved at mount — and the parent mounts a fresh one per open
  // (see `openSeq`), so a tab left open overnight still offers today's date
  // without anything having to reset a field somebody may be typing into.
  const [when, setWhen] = useState(() => isoDate(new Date()));
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!description.trim() || !when || busy) return;
    setBusy(true);
    try {
      await api(`/organisations/${orgId}/changelog`, {
        method: "POST",
        body: JSON.stringify({ description: description.trim(), happened_on: when }),
      });
      onOpenChange(false);
      // Reloaded rather than prepended: the entry belongs at whatever date
      // it was given, which may be well down the list.
      await onAdded();
      toast.add({ title: "Entry recorded" });
    } catch (err) {
      toast.add({ title: "Couldn't record that", description: errorDetail(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a changelog entry</DialogTitle>
          <DialogDescription>
            Everyone in this organisation will see it. The date is the date it happened, which
            needn&rsquo;t be today.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="changelog-date">Date</Label>
            <Input
              id="changelog-date"
              type="date"
              className="w-40"
              value={when}
              onChange={(e) => setWhen(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="changelog-description">What happened</Label>
            <Textarea
              id="changelog-description"
              autoFocus
              rows={4}
              value={description}
              placeholder="BingAds version lift"
              onChange={(e) => setDescription(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit();
              }}
            />
          </div>
        </div>
        <DialogFooter>
          <DialogClose render={<Button variant="ghost">Cancel</Button>} />
          <Button onClick={submit} disabled={!description.trim() || !when || busy}>
            Add entry
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
