import {
  ArchiveIcon,
  ArchiveRestoreIcon,
  FileTextIcon,
  LockIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router-dom";

import { ApiError, api } from "@/api";
import type { Shell } from "@/App";
import { AccessPanel } from "@/components/access-panel";
import { PageHeader } from "@/components/page-header";
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
import {
  Empty,
  EmptyContent,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  EmptyDescription,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useToastManager } from "@/components/ui/toast";
import {
  LEVEL_LABEL,
  canAdminister,
  canEdit,
  personName,
  type Article,
  type Book,
  type BookAccess,
  type Member,
  type Team,
} from "@/lib/types";

export default function BookDetail() {
  const { orgId, bookId } = useParams<{ orgId: string; bookId: string }>();
  const { organisations } = useOutletContext<Shell>();
  const navigate = useNavigate();
  const toast = useToastManager();

  const org = organisations.find((o) => o.id === orgId) ?? null;
  const [book, setBook] = useState<Book | null>(null);
  const [accessInfo, setAccessInfo] = useState<BookAccess | null>(null);
  const [articles, setArticles] = useState<Article[] | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [gone, setGone] = useState(false);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    if (!orgId || !bookId) return;
    try {
      const b = await api<Book>(`/organisations/${orgId}/kb/books/${bookId}`);
      setBook(b);
      const [acc, arts, ms, ts] = await Promise.all([
        api<BookAccess>(`/organisations/${orgId}/kb/books/${bookId}/access`),
        api<Article[]>(`/organisations/${orgId}/kb/books/${bookId}/articles`),
        api<Member[]>(`/organisations/${orgId}/members`),
        api<Team[]>(`/organisations/${orgId}/teams`),
      ]);
      setAccessInfo(acc);
      setArticles(arts);
      setMembers(ms);
      setTeams(ts);
    } catch (err) {
      // 404 here is the access model working: no route in is indistinguishable
      // from not existing.
      if (err instanceof ApiError && err.status === 404) setGone(true);
    }
  }, [orgId, bookId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!org) return null;

  if (gone) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <LockIcon />
          </EmptyMedia>
          <EmptyTitle>You don&rsquo;t have access to this book</EmptyTitle>
          <EmptyDescription>
            It may have been deleted, or never shared with you. A book is private to whoever owns
            it.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button render={<Link to={`/orgs/${org.id}/kb`} />} nativeButton={false}>
            Back to the knowledge base
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  if (!book || !accessInfo || !articles) {
    return (
      <div className="flex flex-1 items-center justify-center py-12">
        <Spinner />
        <span className="sr-only">Loading</span>
      </div>
    );
  }

  const editable = canEdit(book.access);
  const admin = canAdminister(book.access);

  const act = async (fn: () => Promise<unknown>, success: string) => {
    try {
      await fn();
      await load();
      toast.add({ title: success });
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "That didn't work", description: detail });
    }
  };

  return (
    <>
      <PageHeader
        crumbs={[
          { label: org.name, to: `/orgs/${org.id}` },
          { label: "Knowledge base", to: `/orgs/${org.id}/kb` },
          { label: book.name },
        ]}
        title={book.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">{LEVEL_LABEL[book.access]}</Badge>
            {book.archived && <Badge variant="outline">Archived</Badge>}
            <span className="text-muted-foreground">owned by {personName(book.owner)}</span>
          </span>
        }
        actions={
          admin && (
            <Button
              variant="ghost"
              onClick={() =>
                act(
                  () =>
                    api(`/organisations/${org.id}/kb/books/${book.id}`, {
                      method: "PATCH",
                      body: JSON.stringify({ archived: !book.archived }),
                    }),
                  book.archived ? "Restored" : "Archived",
                )
              }
            >
              {book.archived ? <ArchiveRestoreIcon /> : <ArchiveIcon />}
              {book.archived ? "Restore" : "Archive"}
            </Button>
          )
        }
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_24rem]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>About</CardTitle>
            </CardHeader>
            <CardContent>
              <Details book={book} orgId={org.id} editable={editable} onSaved={load} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Articles</CardTitle>
              {editable && (
                <Button size="sm" onClick={() => setCreating(true)}>
                  <PlusIcon />
                  New article
                </Button>
              )}
            </CardHeader>
            <CardContent>
              {articles.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Nothing here yet. Every article starts as your own private draft — publish it
                  from its own page once it&rsquo;s ready.
                </p>
              ) : (
                <ul className="divide-y">
                  {articles.map((article) => (
                    <li key={article.id}>
                      <Link
                        to={`/orgs/${org.id}/kb/articles/${article.id}`}
                        className="flex items-center gap-3 py-2.5 hover:bg-accent/50"
                      >
                        <FileTextIcon className="size-4 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 flex-1 truncate">
                          {article.title || "Untitled"}
                        </span>
                        {article.is_private && (
                          <Badge variant="outline" className="shrink-0">
                            <LockIcon className="size-3" />
                            Private draft
                          </Badge>
                        )}
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {personName(article.owner)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <AccessPanel
            basePath={`/organisations/${org.id}/kb/books/${book.id}`}
            access={accessInfo}
            members={members}
            teams={teams}
            onChanged={load}
          />

          {admin && (
            <DangerZone
              orgId={org.id}
              book={book}
              members={members}
              onDeleted={() => navigate(`/orgs/${org.id}/kb`)}
              onTransferred={load}
            />
          )}
        </div>
      </div>

      <NewArticleDialog
        open={creating}
        onOpenChange={setCreating}
        orgId={org.id}
        bookId={book.id}
        onCreated={(articleId) => navigate(`/orgs/${org.id}/kb/articles/${articleId}`)}
      />
    </>
  );
}

function Details({
  book,
  orgId,
  editable,
  onSaved,
}: {
  book: Book;
  orgId: string;
  editable: boolean;
  onSaved: () => Promise<void>;
}) {
  const toast = useToastManager();
  const [name, setName] = useState(book.name);
  const [description, setDescription] = useState(book.description ?? "");

  if (!editable) {
    return (
      <div className="space-y-2 text-sm">
        <p className={book.description ? "" : "text-muted-foreground"}>
          {book.description || "No description."}
        </p>
        <p className="text-xs text-muted-foreground">
          You have view-only access, so this can&rsquo;t be edited here.
        </p>
      </div>
    );
  }

  const dirty = name !== book.name || description !== (book.description ?? "");

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="name">Name</Label>
        <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="description">Description</Label>
        <Textarea
          id="description"
          rows={4}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <Button
        disabled={!dirty || !name.trim()}
        onClick={async () => {
          await api(`/organisations/${orgId}/kb/books/${book.id}`, {
            method: "PATCH",
            body: JSON.stringify({ name: name.trim(), description }),
          });
          await onSaved();
          toast.add({ title: "Saved" });
        }}
      >
        Save
      </Button>
    </div>
  );
}

function NewArticleDialog({
  open,
  onOpenChange,
  orgId,
  bookId,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgId: string;
  bookId: string;
  onCreated: (articleId: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const article = await api<Article>(`/organisations/${orgId}/kb/books/${bookId}/articles`, {
        method: "POST",
        body: JSON.stringify({ title: title.trim() }),
      });
      setTitle("");
      onOpenChange(false);
      onCreated(article.id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New article</DialogTitle>
          <DialogDescription>
            It starts as your own private draft — nobody else, not even an organisation admin,
            sees it until you publish it.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="article-title">Title</Label>
          <Input
            id="article-title"
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
        </div>
        <DialogFooter>
          <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
          <Button onClick={submit} disabled={busy}>
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DangerZone({
  orgId,
  book,
  members,
  onDeleted,
  onTransferred,
}: {
  orgId: string;
  book: Book;
  members: Member[];
  onDeleted: () => void;
  onTransferred: () => Promise<void>;
}) {
  const toast = useToastManager();
  const [newOwner, setNewOwner] = useState("");
  const [confirmingTransfer, setConfirmingTransfer] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  const candidates = members
    .filter((m) => m.status === "active" && m.user_id && m.user_id !== book.owner?.id)
    .map((m) => ({ value: m.user_id!, label: m.display_name || m.email || "Unknown" }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ownership</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2">
          <Label htmlFor="new-owner">Hand over to</Label>
          <Select items={candidates} value={newOwner} onValueChange={(v) => setNewOwner(String(v))}>
            <SelectTrigger id="new-owner" className="w-full">
              <SelectValue placeholder="Choose someone" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {candidates.map((c) => (
                  <SelectItem key={c.value} value={c.value}>
                    {c.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            disabled={!newOwner}
            onClick={() => setConfirmingTransfer(true)}
          >
            Hand over
          </Button>
        </div>

        <div className="space-y-2 rounded-lg border border-destructive/30 p-3">
          <div className="font-medium">Delete this book</div>
          <p className="text-sm text-muted-foreground">
            Every article in it goes too, for everyone it&rsquo;s shared with.
          </p>
          <Button variant="destructive" onClick={() => setConfirmingDelete(true)}>
            <Trash2Icon />
            Delete
          </Button>
        </div>
      </CardContent>

      <Dialog open={confirmingTransfer} onOpenChange={setConfirmingTransfer}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Hand over {book.name}?</DialogTitle>
            <DialogDescription>
              They become the owner and take control of who can see it.{" "}
              <strong>You will lose access</strong> unless you administer the organisation or
              someone shares it back with you.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
            <Button
              onClick={async () => {
                await api(`/organisations/${orgId}/kb/books/${book.id}/owner`, {
                  method: "POST",
                  body: JSON.stringify({ owner_user_id: newOwner }),
                });
                setConfirmingTransfer(false);
                await onTransferred();
                toast.add({ title: "Handed over" });
              }}
            >
              Hand over
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmingDelete} onOpenChange={setConfirmingDelete}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {book.name}?</DialogTitle>
            <DialogDescription>This cannot be undone. Type the name to confirm.</DialogDescription>
          </DialogHeader>
          <Input
            value={confirmText}
            placeholder={book.name}
            onChange={(e) => setConfirmText(e.target.value)}
          />
          <DialogFooter>
            <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
            <Button
              variant="destructive"
              disabled={confirmText !== book.name}
              onClick={async () => {
                await api(`/organisations/${orgId}/kb/books/${book.id}`, { method: "DELETE" });
                setConfirmingDelete(false);
                toast.add({ title: `${book.name} deleted` });
                onDeleted();
              }}
            >
              Delete permanently
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
