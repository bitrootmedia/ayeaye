import {
  FileIcon,
  MessageSquareIcon,
  PaperclipIcon,
  PencilIcon,
  SendIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, api } from "@/api";
import { Lightbox } from "@/components/lightbox";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useToastManager } from "@/components/ui/toast";
import { useRealtime } from "@/hooks/use-realtime";
import { ago } from "@/lib/format";
import { formatBytes, isAudio, isImage, putToStorage } from "@/lib/storage";
import { VoiceNotePlayer, VoiceNoteRecorder } from "@/components/voice-note";
import { canRecord } from "@/lib/audio";
import { personName, type Person } from "@/lib/types";

type Attachment = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  /** Presigned and short-lived — minted fresh every time the thread is read,
   *  never stored, because a cached one is a dead link waiting to happen. */
  url: string;
  /** null until the worker has made one, and for anything that isn't an
   *  image. The full-size object is the fallback. */
  thumbnail_url?: string | null;
};

type Ticket = { attachment: Attachment; upload_url: string; content_type: string };

type Comment = {
  id: string;
  author: Person | null;
  body: string;
  attachments: Attachment[];
  created_at: string;
  edited_at: string | null;
  deleted: boolean;
  mine: boolean;
};

type Thread = { messages: Comment[]; can_post: boolean; unread: number };

/**
 * Comments on a task or a project.
 *
 * This is the conversation system, not a separate one — which is what makes
 * attachments, voice notes and the unread badge one implementation when they
 * arrive rather than two.
 *
 * **Anyone who can see the thing can comment on it.** A comment is a
 * contribution, not a change to the work, and the commonest reason to share
 * something read-only is to get somebody's input. `can_post` comes from the
 * server; the composer is hidden rather than shown and rejected.
 *
 * Live updates arrive over the socket, which carries **no content** — just
 * "this conversation moved". We refetch, so there is one authorisation path
 * for message bodies instead of two.
 */
export function CommentThread({
  orgId,
  anchor,
  anchorId,
  onChanged,
}: {
  orgId: string;
  anchor: "tasks" | "projects";
  anchorId: string;
  /** Fired when the thread actually moves. A comment can carry a file, and
   *  the task's Files panel shows those — so it has to hear about it. */
  onChanged?: () => void;
}) {
  const toast = useToastManager();
  const [thread, setThread] = useState<Thread | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  // Uploaded and confirmed, waiting for a comment to belong to. They exist
  // server-side already — sending is what gives them a home.
  const [staged, setStaged] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState<{ name: string; pct: number } | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const filePicker = useRef<HTMLInputElement>(null);

  const base = `/organisations/${orgId}/${anchor}/${anchorId}/comments`;

  const load = useCallback(async () => {
    setThread(await api<Thread>(base));
  }, [base]);

  useEffect(() => {
    void load().catch(() => setThread({ messages: [], can_post: false, unread: 0 }));
  }, [load]);

  /** Reload, and tell whoever is listening. Every path that changes the
   *  thread goes through this; the first load doesn't, because nothing has
   *  changed yet and the listener has just fetched for itself. */
  const refresh = useCallback(async () => {
    await load();
    onChanged?.();
  }, [load, onChanged]);

  // Only refetch for *this* thread. The socket is one channel for everything
  // the person can hear about, so without the filter every comment anywhere
  // would refetch every open thread.
  useRealtime(
    useCallback(
      (event) => {
        if (event.anchor?.id === anchorId) void refresh();
      },
      [anchorId, refresh],
    ),
    // Watching is what gets a read-only reader live updates: they have no
    // stake the server would notify, but the thread is on their screen.
    useMemo(
      () => ({ kind: anchor === "tasks" ? ("task" as const) : ("project" as const), id: anchorId }),
      [anchor, anchorId],
    ),
  );

  /** The three-step handshake, from the browser's side.
   *
   *  Takes a Blob rather than a File so a recording goes through exactly the
   *  same path as a picked file — one upload implementation, not two. */
  const upload = async (file: Blob, name: string, type: string): Promise<Attachment | null> => {
    setUploading({ name, pct: 0 });
    try {
      // 1. Ask for a ticket. The server validates the type and stages a row.
      const ticket = await api<Ticket>(
        `/organisations/${orgId}/${anchor}/${anchorId}/attachments`,
        {
          method: "POST",
          body: JSON.stringify({ filename: name, content_type: type }),
        },
      );
      // 2. Bytes go straight to storage, never through the API. Send exactly
      //    the content type the ticket came back with — the signature covers
      //    it byte for byte, and the browser's own `file.type` may carry a
      //    codec parameter the server stripped.
      await putToStorage(ticket.upload_url, file, ticket.content_type, (pct) =>
        setUploading({ name, pct }),
      );
      // 3. Confirm. This is the only point at which the server sees what
      //    actually landed, so it is where the size limit is enforced.
      const ready = await api<Attachment>(
        `/organisations/${orgId}/attachments/${ticket.attachment.id}/confirm`,
        { method: "POST", body: "{}" },
      );
      setStaged((current) => [...current, ready]);
      return ready;
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : String(err);
      toast.add({ title: `Couldn't attach ${name}`, description: detail });
      return null;
    } finally {
      setUploading(null);
    }
  };

  /** A voice note posts in one action: recording it IS the decision to send.
   *  Any typed draft is left alone — that's a separate message. */
  const sendVoiceNote = async (blob: Blob, contentType: string, seconds: number) => {
    const extension = contentType.includes("mp4") ? "m4a" : "webm";
    const ready = await upload(blob, `voice-note-${Math.round(seconds)}s.${extension}`, contentType);
    if (!ready) return;
    try {
      await api(base, {
        method: "POST",
        // A body is required, and "🎤" would be worse than a sentence that
        // reads correctly in an email nudge and a notification title.
        body: JSON.stringify({ body: "Voice note", attachment_ids: [ready.id] }),
      });
      setStaged((current) => current.filter((a) => a.id !== ready.id));
      await refresh();
    } catch {
      toast.add({ title: "Couldn't send that voice note" });
    }
  };

  const send = async () => {
    const body = draft.trim();
    if (!body || sending) return;
    setSending(true);
    try {
      await api(base, {
        method: "POST",
        body: JSON.stringify({ body, attachment_ids: staged.map((a) => a.id) }),
      });
      setDraft("");
      setStaged([]);
      await refresh();
      bottom.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "Couldn't post that", description: detail });
    } finally {
      setSending(false);
    }
  };

  return (
    // A named region, because the same picture can appear both here and in
    // the Files panel above — for a screen reader, and for anything else
    // trying to say *which* copy it means.
    <Card role="region" aria-label="Comments">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MessageSquareIcon className="size-4" />
          Comments
          {thread && thread.messages.length > 0 && (
            <span className="font-mono text-sm font-normal text-muted-foreground">
              {thread.messages.length}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {thread === null ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : thread.messages.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No comments yet. Anyone who can see this can add one.
          </p>
        ) : (
          <ul className="space-y-4">
            {thread.messages.map((comment) => (
              <CommentRow key={comment.id} orgId={orgId} comment={comment} onChanged={refresh} />
            ))}
          </ul>
        )}
        <div ref={bottom} />

        {thread?.can_post && (
          <div className="space-y-2 border-t pt-3">
            {staged.length > 0 && (
              <ul className="flex flex-wrap gap-2">
                {staged.map((file) => (
                  <li
                    key={file.id}
                    className="flex items-center gap-1.5 rounded-md border bg-muted/40 py-1 pr-1 pl-2 text-xs"
                  >
                    <PaperclipIcon className="size-3 shrink-0" />
                    <span className="max-w-40 truncate">{file.filename}</span>
                    <span className="font-mono text-muted-foreground">
                      {formatBytes(file.size_bytes)}
                    </span>
                    <button
                      type="button"
                      aria-label={`Remove ${file.filename}`}
                      className="rounded-sm p-0.5 hover:bg-muted"
                      onClick={() =>
                        setStaged((current) => current.filter((f) => f.id !== file.id))
                      }
                    >
                      <XIcon className="size-3" />
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {uploading && (
              <div className="space-y-1">
                <p className="truncate text-xs text-muted-foreground">
                  Uploading {uploading.name}…
                </p>
                {/* A real progress bar, which is why this uses XHR rather than
                    fetch — a phone video with no feedback reads as a hang. */}
                <div className="h-1 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary transition-[width]"
                    style={{ width: `${Math.round(uploading.pct * 100)}%` }}
                  />
                </div>
              </div>
            )}

            <Textarea
              rows={2}
              value={draft}
              aria-label="Write a comment"
              placeholder="Write a comment…"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                // Enter sends, Shift+Enter breaks the line. A comment box that
                // needs a mouse to submit is one people stop using; a
                // multi-paragraph comment is rarer than a one-line one.
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">
                Enter to send, Shift+Enter for a new line
              </span>
              <span className="flex items-center gap-1">
                <input
                  ref={filePicker}
                  type="file"
                  className="hidden"
                  aria-label="File to upload"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    // Reset first: picking the same file twice in a row fires
                    // no change event otherwise.
                    e.target.value = "";
                    if (file) void upload(file, file.name, file.type);
                  }}
                />
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label="Attach a file"
                  disabled={!!uploading}
                  onClick={() => filePicker.current?.click()}
                >
                  <PaperclipIcon />
                </Button>
                {/* Hidden entirely where the browser can't record, rather than
                    shown and failing at the permission prompt. */}
                {canRecord() && (
                  <VoiceNoteRecorder onRecorded={sendVoiceNote} disabled={!!uploading} />
                )}
                <Button size="sm" disabled={sending || !draft.trim()} onClick={send}>
                  <SendIcon />
                  Comment
                </Button>
              </span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function CommentRow({
  orgId,
  comment,
  onChanged,
}: {
  orgId: string;
  comment: Comment;
  onChanged: () => Promise<void>;
}) {
  const toast = useToastManager();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(comment.body);
  const [viewing, setViewing] = useState<Attachment | null>(null);

  if (comment.deleted) {
    // A tombstone, not a hole: the replies around it still make sense, and
    // silence would be less honest than saying something was removed.
    return (
      <li className="text-sm text-muted-foreground italic">
        {personName(comment.author)} removed a comment
      </li>
    );
  }

  const save = async () => {
    try {
      await api(`/organisations/${orgId}/comments/${comment.id}`, {
        method: "PATCH",
        body: JSON.stringify({ body: value }),
      });
      setEditing(false);
      await onChanged();
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "Couldn't save that", description: detail });
    }
  };

  return (
    <li className="space-y-1">
      <div className="flex items-baseline gap-2">
        <span className="text-sm font-medium">{personName(comment.author)}</span>
        <span className="font-mono text-xs text-muted-foreground">
          {ago(comment.created_at)}
          {comment.edited_at && " · edited"}
        </span>
        {comment.mine && !editing && (
          <span className="ml-auto flex gap-1">
            <Button
              size="sm"
              variant="ghost"
              aria-label="Edit comment"
              onClick={() => setEditing(true)}
            >
              <PencilIcon />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label="Remove comment"
              onClick={async () => {
                await api(`/organisations/${orgId}/comments/${comment.id}`, {
                  method: "DELETE",
                });
                await onChanged();
              }}
            >
              <Trash2Icon />
            </Button>
          </span>
        )}
      </div>
      {editing ? (
        <div className="space-y-2">
          <Textarea
            rows={2}
            value={value}
            aria-label="Edit comment body"
            onChange={(e) => setValue(e.target.value)}
          />
          <div className="flex gap-2">
            {/* Distinct from the task's own Save on the same screen — one
                accessible name per control, or a screen reader can't tell
                them apart either. */}
            <Button size="sm" aria-label="Save comment" onClick={save}>
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <>
          {/* `whitespace-pre-wrap`, so the line breaks someone typed survive. */}
          <p className="text-sm whitespace-pre-wrap">{comment.body}</p>
          {comment.attachments.length > 0 && (
            <ul className="mt-2 flex flex-wrap gap-2">
              {comment.attachments.map((file) => (
                <li key={file.id}>
                  {isAudio(file.content_type) ? (
                    <VoiceNotePlayer url={file.url} filename={file.filename} />
                  ) : isImage(file.content_type) ? (
                    // Shown, not linked as a filename: a photo of the thing
                    // being discussed is the comment, and making people click
                    // to see it defeats attaching it. Clicking opens it full
                    // size in place — the same lightbox the Files panel uses,
                    // so an image behaves the same wherever you meet it.
                    <button
                      type="button"
                      aria-label={`Open ${file.filename}`}
                      className="block overflow-hidden rounded-lg border transition-colors hover:bg-accent/50"
                      onClick={() => setViewing(file)}
                    >
                      <img
                        src={file.thumbnail_url ?? file.url}
                        alt={file.filename}
                        className="max-h-48 max-w-full object-cover"
                      />
                    </button>
                  ) : (
                    <a
                      href={file.url}
                      target="_blank"
                      rel="noreferrer"
                      className="block overflow-hidden rounded-lg border transition-colors hover:bg-accent/50"
                    >
                      <span className="flex items-center gap-2 px-2.5 py-2 text-xs">
                        <FileIcon className="size-4 shrink-0 text-muted-foreground" />
                        <span className="max-w-48 truncate">{file.filename}</span>
                        <span className="font-mono text-muted-foreground">
                          {formatBytes(file.size_bytes)}
                        </span>
                      </span>
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
          {viewing && (
            <Lightbox
              src={viewing.thumbnail_url ?? viewing.url}
              downloadUrl={viewing.url}
              alt={viewing.filename}
              onClose={() => setViewing(null)}
            />
          )}
        </>
      )}
    </li>
  );
}
