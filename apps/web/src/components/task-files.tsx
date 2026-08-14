import {
  AudioLinesIcon,
  FileIcon,
  MessageSquareIcon,
  PaperclipIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "@/api";
import { Lightbox } from "@/components/lightbox";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToastManager } from "@/components/ui/toast";
import { ago } from "@/lib/format";
import { formatBytes, isAudio, isImage, putToStorage } from "@/lib/storage";
import { personName, type TaskFile } from "@/lib/types";

type Ticket = {
  attachment: { id: string; filename: string };
  upload_url: string;
  content_type: string;
};

/**
 * Every file on a task, in one place.
 *
 * **One panel, not two.** A file dropped into a comment is exactly as much "a
 * file on this task" as one added here, and the question people ask is "where
 * is the survey PDF", never "was it attached or posted". So both appear
 * together and the comment-sourced ones are marked — you can still find the
 * discussion, you just don't have to scroll a thread to find the file.
 *
 * Uploads go **browser → storage** through the same three-step handshake the
 * comment composer uses; see lib/storage.ts. Nothing here proxies bytes.
 */
export function TaskFilesPanel({
  orgId,
  taskId,
  canEdit,
  /** Bumped by the thread when a comment is posted or removed. */
  refreshKey,
}: {
  orgId: string;
  taskId: string;
  canEdit: boolean;
  refreshKey?: number;
}) {
  const toast = useToastManager();
  const [files, setFiles] = useState<TaskFile[] | null>(null);
  const [uploading, setUploading] = useState<{ name: string; percent: number } | null>(null);
  const [viewing, setViewing] = useState<TaskFile | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setFiles(await api<TaskFile[]>(`/organisations/${orgId}/tasks/${taskId}/files`));
    } catch {
      setFiles([]);
    }
  }, [orgId, taskId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const upload = async (file: File) => {
    setUploading({ name: file.name, percent: 0 });
    try {
      const ticket = await api<Ticket>(`/organisations/${orgId}/tasks/${taskId}/files`, {
        method: "POST",
        body: JSON.stringify({ filename: file.name, content_type: file.type }),
      });
      // The signed type, not the browser's — SigV4 covers Content-Type byte
      // for byte and the server normalised it.
      await putToStorage(ticket.upload_url, file, ticket.content_type, (fraction) =>
        setUploading({ name: file.name, percent: Math.round(fraction * 100) }),
      );
      await api(`/organisations/${orgId}/attachments/${ticket.attachment.id}/confirm`, {
        method: "POST",
      });
      await load();
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "That file didn't upload", description: detail });
    } finally {
      setUploading(null);
      if (input.current) input.current.value = "";
    }
  };

  const remove = async (file: TaskFile) => {
    try {
      await api(`/organisations/${orgId}/tasks/${taskId}/files/${file.id}`, {
        method: "DELETE",
      });
      await load();
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "Couldn't remove that", description: detail });
    }
  };

  return (
    // Named, because a file posted in a comment appears both here and in the
    // thread below, and "the picture" has to be able to mean one of them.
    <Card role="region" aria-label="Files">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <PaperclipIcon className="size-4" />
          Files
          {files && files.length > 0 && (
            <span className="font-mono text-xs font-normal text-muted-foreground">
              {files.length}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {files && files.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Nothing attached yet. Files posted in comments show up here too.
          </p>
        )}

        {files && files.length > 0 && (
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {files.map((file) => (
              <li key={file.id} className="group relative">
                <FileTile file={file} onOpen={() => setViewing(file)} />
                {/* A comment file is deleted by deleting its comment —
                    removing it from under a message would leave the comment
                    pointing at nothing. */}
                {canEdit && !file.from_comment && (
                  <Button
                    size="icon"
                    variant="secondary"
                    aria-label={`Remove ${file.filename}`}
                    className="absolute top-1 right-1 size-6 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                    onClick={() => remove(file)}
                  >
                    <Trash2Icon className="size-3.5" />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}

        {uploading && (
          <div className="space-y-1">
            <p className="truncate text-xs text-muted-foreground">
              Uploading {uploading.name}… {uploading.percent}%
            </p>
            <div className="h-1 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full bg-primary transition-[width]"
                style={{ width: `${uploading.percent}%` }}
              />
            </div>
          </div>
        )}

        {canEdit && (
          <>
            <input
              ref={input}
              type="file"
              className="sr-only"
              aria-label="File to add to this task"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void upload(file);
              }}
            />
            <Button
              variant="outline"
              size="sm"
              disabled={!!uploading}
              aria-label="Add a file"
              onClick={() => input.current?.click()}
            >
              <PaperclipIcon />
              Add a file
            </Button>
          </>
        )}
      </CardContent>

      {viewing && (
        <Lightbox
          src={viewing.thumbnail_url ?? viewing.url}
          downloadUrl={viewing.url}
          alt={viewing.filename}
          onClose={() => setViewing(null)}
        />
      )}
    </Card>
  );
}

function FileTile({ file, onOpen }: { file: TaskFile; onOpen: () => void }) {
  const image = isImage(file.content_type);
  const caption = (
    <span className="block space-y-0.5 p-2 text-left">
      <span className="block truncate text-xs font-medium">{file.filename}</span>
      <span className="flex items-center gap-1 font-mono text-[0.6875rem] text-muted-foreground">
        {formatBytes(file.size_bytes)}
        {file.from_comment && (
          <MessageSquareIcon
            className="size-3"
            aria-label="Posted in a comment"
            /* Marked, not separated — the panel stays one list. */
          />
        )}
      </span>
    </span>
  );

  const preview = image ? (
    // `thumbnail_url` is null until the worker has run. Falling back to the
    // original costs bandwidth for a few seconds; showing a broken tile costs
    // trust in the upload.
    <img
      src={file.thumbnail_url ?? file.url}
      alt={file.filename}
      loading="lazy"
      className="h-24 w-full bg-muted object-cover"
    />
  ) : (
    <span className="flex h-24 w-full items-center justify-center bg-muted/50">
      {isAudio(file.content_type) ? (
        <AudioLinesIcon className="size-7 text-muted-foreground" />
      ) : (
        <FileIcon className="size-7 text-muted-foreground" />
      )}
    </span>
  );

  const shell =
    "block w-full overflow-hidden rounded-lg border transition-colors hover:bg-accent/50";
  // Provenance on hover rather than a third line: four tiles a row have no
  // space for it, and it's the answer to a follow-up question, not the first.
  const who = `${personName(file.uploaded_by)} · ${ago(file.created_at)}`;

  // Images open here; anything else is a download, and a link is the honest
  // control for that — middle-click and "save as" both work.
  return image ? (
    <button
      type="button"
      className={shell}
      title={who}
      aria-label={`Open ${file.filename}`}
      onClick={onOpen}
    >
      {preview}
      {caption}
    </button>
  ) : (
    <a
      href={file.url}
      target="_blank"
      rel="noreferrer"
      className={shell}
      title={who}
      aria-label={`Open ${file.filename}`}
    >
      {preview}
      {caption}
    </a>
  );
}
