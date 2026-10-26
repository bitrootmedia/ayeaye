import { ArchiveRestoreIcon, BotIcon, HistoryIcon, PencilIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api, apiWithHeaders } from "@/api";
import { TagStrip } from "@/components/tag-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { useToastManager } from "@/components/ui/toast";
import { ago } from "@/lib/format";
import { personName, type Fact } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Rows per page, and how much "Show more" adds — the changelog's number. */
const PAGE = 50;

// The one limit the API enforces; refused rather than cut, so say so first.
const MAX_FACT_LENGTH = 4000;

/**
 * A book's facts: the few sentences somebody — or their assistant — wrote
 * down so the next person finds them.
 *
 * **Plain text, never `dangerouslySetInnerHTML`**, the changelog's and
 * Sparks' safe-by-construction position: a fact is what an assistant writes
 * mid-task over MCP, and nothing it sends is ever parsed as markup here.
 *
 * Newest first and paged, because facts only accumulate. Superseded ones are
 * out of the list by default and one toggle away, struck through and
 * pointing at what replaced them — knowledge rots, and "this was true until
 * then" is the honest record of it.
 *
 * `highlight` is a fact id from the URL (`?fact=…`), which is how a ⌘K or
 * recall hit lands here: a fact has no screen of its own, so the link is to
 * its book with the fact picked out and scrolled to.
 */
export function FactsPanel({
  orgId,
  bookId,
  editable,
  highlight,
}: {
  orgId: string;
  bookId: string;
  editable: boolean;
  highlight: string | null;
}) {
  const toast = useToastManager();
  const [facts, setFacts] = useState<Fact[] | null>(null);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(PAGE);
  // A highlighted fact may itself be superseded; showing them is the only
  // way the link can arrive somewhere that contains it.
  const [showSuperseded, setShowSuperseded] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<Fact | null>(null);

  const load = useCallback(async () => {
    const res = await apiWithHeaders<Fact[]>(
      `/organisations/${orgId}/kb/books/${bookId}/facts?limit=${limit}` +
        `&include_superseded=${showSuperseded || Boolean(highlight)}`,
    );
    setFacts(res.data);
    setTotal(Number(res.headers.get("X-Total-Count") ?? res.data.length));
  }, [orgId, bookId, limit, showSuperseded, highlight]);

  useEffect(() => {
    void load().catch(() => setFacts([]));
  }, [load]);

  const failed = (err: unknown, title: string) => {
    const detail =
      err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
    toast.add({ title, description: detail });
  };

  const add = async () => {
    const body = draft.trim();
    if (!body || busy) return;
    setBusy(true);
    try {
      await api(`/organisations/${orgId}/kb/books/${bookId}/facts`, {
        method: "POST",
        body: JSON.stringify({ body }),
      });
      setDraft("");
      await load();
    } catch (err) {
      failed(err, "Couldn't add that");
    } finally {
      setBusy(false);
    }
  };

  const act = async (path: string, init: RequestInit, title: string) => {
    try {
      await api(`/organisations/${orgId}/kb/facts/${path}`, init);
      await load();
    } catch (err) {
      failed(err, title);
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Facts</CardTitle>
        <Button
          size="sm"
          variant="ghost"
          className="text-muted-foreground"
          onClick={() => setShowSuperseded((v) => !v)}
        >
          <HistoryIcon />
          {showSuperseded ? "Hide superseded" : "Show superseded"}
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {editable && (
          <div className="space-y-2">
            <Textarea
              aria-label="New fact"
              rows={2}
              value={draft}
              placeholder="Something worth knowing next time — a gotcha, a decision and why, what an incident turned out to be."
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                // ⌘/Ctrl+Enter adds; a bare Enter is a new line.
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void add();
              }}
            />
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs text-muted-foreground">
                Everyone this book is shared with sees it straight away. Never a password or a key.
              </p>
              <Button
                size="sm"
                disabled={!draft.trim() || draft.trim().length > MAX_FACT_LENGTH || busy}
                onClick={add}
              >
                Add fact
              </Button>
            </div>
          </div>
        )}

        {facts === null ? null : facts.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No facts yet. They&rsquo;re short things worth knowing — anything with steps belongs in
            an article.
          </p>
        ) : (
          <ul className="divide-y">
            {facts.map((fact) => (
              <FactRow
                key={fact.id}
                orgId={orgId}
                bookId={bookId}
                fact={fact}
                highlighted={fact.id === highlight}
                onChanged={load}
                onSave={(body) =>
                  act(
                    fact.id,
                    { method: "PATCH", body: JSON.stringify({ body }) },
                    "Couldn't save that",
                  )
                }
                onSupersede={() =>
                  act(`${fact.id}/supersede`, { method: "POST", body: "{}" }, "Couldn't do that")
                }
                onRestore={() =>
                  act(`${fact.id}/restore`, { method: "POST", body: "{}" }, "Couldn't do that")
                }
                onDelete={() => setDeleting(fact)}
              />
            ))}
          </ul>
        )}

        {facts !== null && total > facts.length && (
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>
              Showing {facts.length} of {total}
            </span>
            <Button variant="outline" size="sm" onClick={() => setLimit((n) => n + PAGE)}>
              Show more
            </Button>
          </div>
        )}
      </CardContent>

      <Dialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this fact?</DialogTitle>
            <DialogDescription>
              For a fact that was simply wrong. If it was true once and has stopped being, mark it
              superseded instead — it leaves recall but the record stays.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
            <Button
              variant="destructive"
              onClick={async () => {
                const target = deleting;
                setDeleting(null);
                if (target) await act(target.id, { method: "DELETE" }, "Couldn't delete that");
              }}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function FactRow({
  orgId,
  bookId,
  fact,
  highlighted,
  onChanged,
  onSave,
  onSupersede,
  onRestore,
  onDelete,
}: {
  orgId: string;
  bookId: string;
  fact: Fact;
  highlighted: boolean;
  onChanged: () => Promise<void>;
  onSave: (body: string) => Promise<void>;
  onSupersede: () => Promise<void>;
  onRestore: () => Promise<void>;
  onDelete: () => void;
}) {
  const row = useRef<HTMLLIElement>(null);
  const [editing, setEditing] = useState(false);
  // Seeded when the editor opens — the changelog row's reason.
  const [body, setBody] = useState(fact.body);
  const superseded = fact.superseded_at !== null;
  // Enough to tell two rows apart in an accessible name; tests address the
  // row's buttons by it.
  const label = fact.body.slice(0, 40);

  useEffect(() => {
    if (highlighted) row.current?.scrollIntoView({ block: "center" });
  }, [highlighted]);

  const commit = () => {
    if (!body.trim()) return;
    setEditing(false);
    void onSave(body.trim());
  };

  return (
    <li
      ref={row}
      id={`fact-${fact.id}`}
      className={cn(
        "space-y-2 py-3",
        highlighted && "-mx-2 rounded-lg bg-accent/60 px-2",
      )}
    >
      {editing ? (
        <div className="space-y-2">
          <Textarea
            autoFocus
            aria-label={`Edit ${label}`}
            rows={3}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) commit();
              if (e.key === "Escape") setEditing(false);
            }}
          />
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button size="sm" disabled={!body.trim()} onClick={commit}>
              Save
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-2">
          <p
            className={cn(
              "min-w-0 flex-1 text-sm whitespace-pre-wrap",
              superseded && "text-muted-foreground line-through",
            )}
          >
            {fact.body}
          </p>
          {fact.can_edit && (
            <div className="flex shrink-0 items-center gap-1">
              {!superseded && (
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Edit ${label}`}
                  onClick={() => {
                    setBody(fact.body);
                    setEditing(true);
                  }}
                >
                  <PencilIcon />
                </Button>
              )}
              {superseded ? (
                <Button size="sm" variant="ghost" aria-label={`Restore ${label}`} onClick={onRestore}>
                  <ArchiveRestoreIcon />
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-muted-foreground"
                  onClick={onSupersede}
                  aria-label={`Supersede ${label}`}
                >
                  No longer true
                </Button>
              )}
              {fact.can_delete && (
                <Button size="sm" variant="ghost" aria-label={`Delete ${label}`} onClick={onDelete}>
                  <Trash2Icon />
                </Button>
              )}
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
        <span className="font-mono tabular-nums" title={fact.created_at}>
          {ago(fact.created_at)}
        </span>
        <span>
          {fact.written_by ? personName(fact.written_by) : "A former member"}
          {fact.updated_at !== fact.created_at && " · edited"}
        </span>
        {fact.via && (
          // Attribution, not authorship — the comment thread's "via" badge.
          <Badge variant="outline" className="gap-1 font-normal">
            <BotIcon className="size-3" />
            via {fact.via}
          </Badge>
        )}
        {superseded && (
          <span>
            Superseded
            {fact.superseded_by_fact_id && (
              <>
                {" by "}
                <Link
                  className="underline underline-offset-2"
                  to={`/orgs/${orgId}/kb/books/${bookId}?fact=${fact.superseded_by_fact_id}`}
                >
                  a newer fact
                </Link>
              </>
            )}
          </span>
        )}
        <TagStrip
          orgId={orgId}
          basePath={`/organisations/${orgId}/kb/facts/${fact.id}`}
          tags={fact.tags}
          editable={fact.can_edit}
          onChanged={onChanged}
          noun="fact"
        />
      </div>
    </li>
  );
}
