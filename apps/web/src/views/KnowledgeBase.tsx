import { ArchiveIcon, BookOpenIcon, PlusIcon, SearchIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router-dom";

import { api } from "@/api";
import type { Shell } from "@/App";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  EmptyContent,
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
import { LEVEL_LABEL, personName, type Book } from "@/lib/types";

/**
 * Every book you can see — trimmed from `Projects.tsx`, same reasoning:
 * a book is private to its owner until it's shared, so this list is
 * genuinely different for every person. No groups, no board/table toggle —
 * the structure here is flat, book → article, nothing deeper.
 */
export default function KnowledgeBase() {
  const { orgId } = useParams<{ orgId: string }>();
  const { organisations } = useOutletContext<Shell>();
  const toast = useToastManager();

  const org = organisations.find((o) => o.id === orgId) ?? null;
  const [books, setBooks] = useState<Book[] | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    if (!orgId) return;
    setBooks(await api<Book[]>(`/organisations/${orgId}/kb/books?include_archived=${showArchived}`));
  }, [orgId, showArchived]);

  useEffect(() => {
    void load().catch(() => setBooks([]));
  }, [load]);

  if (!org) return null;

  const q = query.trim().toLowerCase();
  const filtered = q ? (books ?? []).filter((b) => b.name.toLowerCase().includes(q)) : (books ?? []);

  return (
    <>
      <PageHeader
        crumbs={[{ label: org.name, to: `/orgs/${org.id}` }, { label: "Knowledge base" }]}
        title="Knowledge base"
        description="Runbooks, policies, anything worth writing down once and finding again."
        actions={
          <>
            <div className="relative">
              <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                aria-label="Filter by name"
                placeholder="Filter by name…"
                className="w-48 pl-8"
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <Button variant="ghost" onClick={() => setShowArchived((v) => !v)}>
              <ArchiveIcon />
              {showArchived ? "Hide archived" : "Show archived"}
            </Button>
            <Button onClick={() => setCreating(true)}>
              <PlusIcon />
              New book
            </Button>
          </>
        }
      />

      {books === null ? (
        <div className="flex flex-1 items-center justify-center py-12">
          <Spinner />
        </div>
      ) : books.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <BookOpenIcon />
            </EmptyMedia>
            <EmptyTitle>Nothing here yet</EmptyTitle>
            <EmptyDescription>
              A book is private to whoever creates it, so this list only shows what you own or
              what someone has shared with you. There may be others you can&rsquo;t see.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => setCreating(true)}>
              <PlusIcon />
              New book
            </Button>
          </EmptyContent>
        </Empty>
      ) : filtered.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground">
          No books match &ldquo;{query.trim()}&rdquo;.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((book) => (
            <Link
              key={book.id}
              to={`/orgs/${org.id}/kb/books/${book.id}`}
              className="flex flex-col gap-3 rounded-xl border bg-card p-4 hover:bg-accent/50"
            >
              <div className="min-w-0">
                <div className="flex items-start gap-2">
                  <span className="min-w-0 flex-1 truncate font-medium">{book.name}</span>
                  {book.archived && (
                    <Badge variant="outline" className="shrink-0 text-muted-foreground">
                      Archived
                    </Badge>
                  )}
                </div>
                {book.description && (
                  <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                    {book.description}
                  </p>
                )}
              </div>
              <div className="mt-auto flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <span className="truncate">{personName(book.owner)}</span>
                <Badge variant="outline" className="shrink-0">
                  {LEVEL_LABEL[book.access]}
                </Badge>
              </div>
            </Link>
          ))}
        </div>
      )}

      <NewBookDialog
        open={creating}
        onOpenChange={setCreating}
        orgId={org.id}
        onCreated={async () => {
          await load();
          toast.add({
            title: "Book created",
            description: "Only you can see it — share it from its Access panel.",
          });
        }}
      />
    </>
  );
}

function NewBookDialog({
  open,
  onOpenChange,
  orgId,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgId: string;
  onCreated: () => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      await api(`/organisations/${orgId}/kb/books`, {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), description: description.trim() || null }),
      });
      setName("");
      setDescription("");
      onOpenChange(false);
      await onCreated();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New book</DialogTitle>
          <DialogDescription>
            You&rsquo;ll own it, and to begin with nobody else can see it — not even the rest of
            the organisation. Share it once it exists.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="book-name">Name</Label>
            <Input
              id="book-name"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="book-description">Description</Label>
            <Textarea
              id="book-description"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
          <Button onClick={submit} disabled={busy || !name.trim()}>
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
