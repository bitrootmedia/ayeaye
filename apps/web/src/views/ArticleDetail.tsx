import { HistoryIcon, LockIcon, Trash2Icon, UnlockIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router-dom";

import { ApiError, api } from "@/api";
import type { Shell } from "@/App";
import { FilesPanel } from "@/components/files-panel";
import { PageHeader } from "@/components/page-header";
import { RichText, RichTextEditor } from "@/components/rich-text";
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
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useToastManager } from "@/components/ui/toast";
import { ago } from "@/lib/format";
import { canAdminister, canEdit, personName, type Article, type ArticleRevision, type Book } from "@/lib/types";

// Same debounce as the notepad and the task's private note — long enough
// not to write on every keystroke, short enough that leaving quickly still
// saves.
const AUTOSAVE_MS = 800;

export default function ArticleDetail() {
  const { orgId, articleId } = useParams<{ orgId: string; articleId: string }>();
  const { organisations } = useOutletContext<Shell>();
  const navigate = useNavigate();
  const toast = useToastManager();

  const org = organisations.find((o) => o.id === orgId) ?? null;
  const [article, setArticle] = useState<Article | null>(null);
  const [book, setBook] = useState<Book | null>(null);
  const [revision, setRevision] = useState<ArticleRevision | null>(null);
  const [gone, setGone] = useState(false);
  const [filesKey, setFilesKey] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  const load = useCallback(async () => {
    if (!orgId || !articleId) return;
    try {
      const a = await api<Article>(`/organisations/${orgId}/kb/articles/${articleId}`);
      setArticle(a);
      const b = await api<Book>(`/organisations/${orgId}/kb/books/${a.book_id}`);
      setBook(b);
      if (canEdit(a.access)) {
        // A session's own revision, created if none exists yet — see
        // services/articles.py::start_editing_session. Mutable for the rest
        // of this visit; a later visit either reuses it (same person, still
        // within the idle window) or seeds a fresh one from it.
        const rev = await api<ArticleRevision>(
          `/organisations/${orgId}/kb/articles/${articleId}/edit-session`,
          { method: "POST" },
        );
        setRevision(rev);
      } else {
        // Read-only: just show the current revision, no session to open.
        const revs = await api<ArticleRevision[]>(
          `/organisations/${orgId}/kb/articles/${articleId}/revisions`,
        );
        setRevision(revs.find((r) => r.is_current) ?? revs[0] ?? null);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setGone(true);
    }
  }, [orgId, articleId]);

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
          <EmptyTitle>You don&rsquo;t have access to this article</EmptyTitle>
          <EmptyDescription>
            It may have been deleted, made private by its owner, or never shared with you.
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

  if (!article || !book || !revision) {
    return (
      <div className="flex flex-1 items-center justify-center py-12">
        <Spinner />
        <span className="sr-only">Loading</span>
      </div>
    );
  }

  const editable = canEdit(article.access);
  const admin = canAdminister(article.access);

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
          { label: book.name, to: `/orgs/${org.id}/kb/books/${book.id}` },
          { label: article.title || "Untitled" },
        ]}
        title={article.title || "Untitled"}
        description={
          <span className="flex flex-wrap items-center gap-2">
            {article.is_private ? (
              <Badge variant="outline">
                <LockIcon className="size-3" />
                Private draft
              </Badge>
            ) : (
              <Badge variant="outline">Published</Badge>
            )}
            <span className="text-muted-foreground">owned by {personName(article.owner)}</span>
          </span>
        }
        actions={
          <>
            <Button variant="ghost" onClick={() => setHistoryOpen(true)}>
              <HistoryIcon />
              History
            </Button>
            {article.can_make_private && (
              <Button
                variant="ghost"
                onClick={() =>
                  act(
                    () =>
                      api(`/organisations/${org.id}/kb/articles/${article.id}/private`, {
                        method: "PATCH",
                        body: JSON.stringify({ is_private: !article.is_private }),
                      }),
                    article.is_private ? "Published" : "Made private",
                  )
                }
              >
                {article.is_private ? <UnlockIcon /> : <LockIcon />}
                {article.is_private ? "Publish" : "Make private"}
              </Button>
            )}
          </>
        }
      />

      {article.is_private && (
        <p className="-mt-2 text-xs text-muted-foreground">
          Only you can see this. Anyone who can see {book.name} will be able to once you publish
          it.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-4">
          <Card>
            <CardContent className="pt-6">
              <Editor
                orgId={org.id}
                revision={revision}
                editable={editable}
                onImageAdded={() => setFilesKey((k) => k + 1)}
                onSaved={(rev) => {
                  setRevision(rev);
                  setArticle((a) => (a ? { ...a, title: rev.title } : a));
                }}
              />
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <FilesPanel
            orgId={org.id}
            basePath={`/organisations/${org.id}/kb/revisions/${revision.id}`}
            canEdit={editable}
            refreshKey={filesKey}
          />

          {admin && (
            <Card>
              <CardHeader>
                <CardTitle>Delete</CardTitle>
              </CardHeader>
              <CardContent>
                <Button variant="destructive" onClick={() => setConfirmingDelete(true)}>
                  <Trash2Icon />
                  Delete this article
                </Button>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <HistoryDialog
        open={historyOpen}
        onOpenChange={setHistoryOpen}
        orgId={org.id}
        articleId={article.id}
      />

      <Dialog
        open={confirmingDelete}
        onOpenChange={(open) => {
          setConfirmingDelete(open);
          if (!open) setConfirmText("");
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {article.title || "this article"}?</DialogTitle>
            <DialogDescription>
              This removes it and every revision, along with its files. It cannot be undone. Type
              the title to confirm.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={confirmText}
            placeholder={article.title}
            onChange={(e) => setConfirmText(e.target.value)}
          />
          <DialogFooter>
            <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
            <Button
              variant="destructive"
              disabled={confirmText !== article.title}
              onClick={async () => {
                await api(`/organisations/${org.id}/kb/articles/${article.id}`, {
                  method: "DELETE",
                });
                toast.add({ title: "Deleted" });
                navigate(`/orgs/${org.id}/kb/books/${book.id}`);
              }}
            >
              Delete permanently
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/**
 * Title + body, autosaved into the session's mutable revision.
 *
 * Read-only when the caller doesn't have `write`: no session was opened, so
 * there is nothing to autosave into — just the rendered current revision.
 */
function Editor({
  orgId,
  revision,
  editable,
  onImageAdded,
  onSaved,
}: {
  orgId: string;
  revision: ArticleRevision;
  editable: boolean;
  onImageAdded: () => void;
  onSaved: (revision: ArticleRevision) => void;
}) {
  const toast = useToastManager();
  const [title, setTitle] = useState(revision.title);
  const [body, setBody] = useState(revision.body);
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  // Write/Preview, the same pair GitHub's own markdown fields use — a
  // mermaid diagram only renders in RichText's read-only path, so without
  // this the person actually drawing one would never see it themselves.
  const [mode, setMode] = useState<"write" | "preview">("write");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Title and body share one debounce window — see Notepad.tsx for why two
  // independent timers silently drop whichever field wasn't touched last.
  const pending = useRef<{ title?: string; body?: string }>({});
  // Unlike the notepad's PATCH, this endpoint has no partial-update shape —
  // `autosave_revision` always overwrites both fields — so a save has to
  // send the *current* value of whichever field didn't just change, never a
  // value captured in a stale closure. Refs, updated on every keystroke,
  // rather than the `title`/`body` state `save` would otherwise close over.
  const titleRef = useRef(revision.title);
  const bodyRef = useRef(revision.body);

  useEffect(() => {
    setTitle(revision.title);
    setBody(revision.body);
    titleRef.current = revision.title;
    bodyRef.current = revision.body;
    pending.current = {};
  }, [revision.id]);

  const save = useCallback(
    async (fields: { title?: string; body?: string }) => {
      if (Object.keys(fields).length === 0) return;
      setState("saving");
      try {
        const saved = await api<ArticleRevision>(
          `/organisations/${orgId}/kb/revisions/${revision.id}`,
          {
            method: "PATCH",
            body: JSON.stringify({
              title: fields.title ?? titleRef.current,
              body: fields.body ?? bodyRef.current,
            }),
          },
        );
        setState("saved");
        onSaved(saved);
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          toast.add({
            title: "This article changed elsewhere",
            description: "Reload the page to keep editing the latest version.",
          });
          setState("idle");
          return;
        }
        // Never claim a save that didn't happen — the next edit retries.
        setState("idle");
        pending.current = { ...fields, ...pending.current };
      }
    },
    [orgId, revision.id, onSaved, toast],
  );

  const flush = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    const fields = pending.current;
    pending.current = {};
    if (Object.keys(fields).length > 0) void save(fields);
  }, [save]);

  const queueSave = (fields: { title?: string; body?: string }) => {
    if (fields.title !== undefined) titleRef.current = fields.title;
    if (fields.body !== undefined) bodyRef.current = fields.body;
    setState("idle");
    pending.current = { ...pending.current, ...fields };
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(flush, AUTOSAVE_MS);
  };

  useEffect(() => () => flush(), [flush]);

  useEffect(() => {
    const warnIfPending = (e: BeforeUnloadEvent) => {
      if (timer.current !== null || Object.keys(pending.current).length > 0) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warnIfPending);
    return () => window.removeEventListener("beforeunload", warnIfPending);
  }, []);

  if (!editable) {
    return (
      <div className="space-y-4">
        <h2 className="text-xl font-semibold">{revision.title || "Untitled"}</h2>
        <RichText html={revision.body} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Input
        aria-label="Article title"
        placeholder="Untitled"
        value={title}
        className="border-none px-0 text-xl font-semibold shadow-none focus-visible:ring-0"
        onChange={(e) => {
          setTitle(e.target.value);
          queueSave({ title: e.target.value });
        }}
        onBlur={flush}
      />
      <div className="flex items-center gap-1 text-xs">
        <Button
          type="button"
          size="sm"
          variant={mode === "write" ? "secondary" : "ghost"}
          onClick={() => setMode("write")}
        >
          Write
        </Button>
        <Button
          type="button"
          size="sm"
          variant={mode === "preview" ? "secondary" : "ghost"}
          onClick={() => setMode("preview")}
        >
          Preview
        </Button>
      </div>
      {mode === "write" ? (
        <RichTextEditor
          orgId={orgId}
          basePath={`/organisations/${orgId}/kb/revisions/${revision.id}`}
          value={body}
          noun="article"
          onChange={(html) => {
            setBody(html);
            queueSave({ body: html });
          }}
          onImageAdded={onImageAdded}
        />
      ) : body ? (
        <div className="rounded-lg border px-3 py-2">
          <RichText html={body} />
        </div>
      ) : (
        <p className="rounded-lg border px-3 py-2 text-sm text-muted-foreground">
          Nothing to preview yet.
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        {state === "saving" ? "Saving…" : "Saved automatically"}
      </p>
    </div>
  );
}

function HistoryDialog({
  open,
  onOpenChange,
  orgId,
  articleId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgId: string;
  articleId: string;
}) {
  const [revisions, setRevisions] = useState<ArticleRevision[] | null>(null);
  const [viewing, setViewing] = useState<ArticleRevision | null>(null);

  useEffect(() => {
    if (!open) {
      setRevisions(null);
      setViewing(null);
      return;
    }
    void api<ArticleRevision[]>(`/organisations/${orgId}/kb/articles/${articleId}/revisions`).then(
      setRevisions,
    );
  }, [open, orgId, articleId]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{viewing ? viewing.title || "Untitled" : "History"}</DialogTitle>
          <DialogDescription>
            {viewing
              ? `Edited by ${personName(viewing.edited_by)} · ${ago(viewing.created_at)}`
              : "Every editing session, newest first. Each one is frozen the moment a later session starts."}
          </DialogDescription>
        </DialogHeader>
        {viewing ? (
          <div className="max-h-[60vh] space-y-4 overflow-y-auto">
            <Button variant="ghost" size="sm" onClick={() => setViewing(null)}>
              Back to the list
            </Button>
            <RichText html={viewing.body} />
          </div>
        ) : revisions === null ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : (
          <ul className="max-h-[60vh] divide-y overflow-y-auto">
            {revisions.map((rev) => (
              <li key={rev.id}>
                <button
                  type="button"
                  className="flex w-full items-center justify-between gap-3 py-2.5 text-left hover:bg-accent/50"
                  onClick={() => setViewing(rev)}
                >
                  <span className="min-w-0 flex-1 truncate">{rev.title || "Untitled"}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {personName(rev.edited_by)} · {ago(rev.created_at)}
                  </span>
                  {rev.is_current && (
                    <Badge variant="outline" className="shrink-0">
                      Current
                    </Badge>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
        <DialogFooter>
          <DialogClose render={<Button variant="ghost" />}>Close</DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
