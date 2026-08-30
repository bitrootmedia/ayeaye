import { NotebookIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useOutletContext, useParams } from "react-router-dom";

import { api } from "@/api";
import type { Shell } from "@/App";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { ago } from "@/lib/format";
import type { PersonalNote } from "@/lib/types";

/** Same debounce as the task's own private note — long enough not to write
 *  on every keystroke, short enough that closing the tab doesn't lose a
 *  sentence. */
const AUTOSAVE_MS = 800;

/**
 * The notepad: free-form personal notes, scoped to this organisation.
 *
 * **Only you, ever — no sharing, no admin override.** The same
 * absence-of-a-branch promise `PrivateNote` makes for a task, extended to a
 * whole list: `services/personal_notes.py` filters on the caller in every
 * statement, full stop. This screen doesn't add a second thing to that
 * promise, it just gives it a title and a delete button, which a note
 * anchored to one task doesn't need.
 *
 * **Autosaved, no Save button** — editing a note is the identical trade
 * `PrivateNote` already made: a button turns a scratchpad into a form you
 * can fail to submit, and the failure mode is losing the thought.
 */
export default function Notepad() {
  const { orgId } = useParams<{ orgId: string }>();
  const { organisations } = useOutletContext<Shell>();
  const org = organisations.find((o) => o.id === orgId) ?? null;

  const [notes, setNotes] = useState<PersonalNote[] | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    if (!orgId) return;
    setNotes(await api<PersonalNote[]>(`/organisations/${orgId}/notes`).catch(() => []));
  }, [orgId]);

  useEffect(() => {
    void load();
  }, [load]);

  const createNote = async () => {
    if (!orgId || creating) return;
    setCreating(true);
    try {
      const note = await api<PersonalNote>(`/organisations/${orgId}/notes`, {
        method: "POST",
        body: JSON.stringify({ title: "Untitled note", body: "" }),
      });
      await load();
      setOpenId(note.id);
    } finally {
      setCreating(false);
    }
  };

  const removeNote = async (id: string) => {
    if (!orgId) return;
    await api(`/organisations/${orgId}/notes/${id}`, { method: "DELETE" });
    if (openId === id) setOpenId(null);
    await load();
  };

  if (!org) return null;

  const openNote = notes?.find((n) => n.id === openId) ?? null;

  return (
    <>
      <PageHeader
        title="Notes"
        description="Yours alone — nobody else can see these, not even organisation admins."
        actions={
          <Button onClick={createNote} disabled={creating}>
            <PlusIcon />
            New note
          </Button>
        }
      />

      {notes === null ? (
        <div className="flex flex-1 items-center justify-center py-12">
          <Spinner />
        </div>
      ) : notes.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <NotebookIcon />
            </EmptyMedia>
            <EmptyTitle>Nothing jotted down yet</EmptyTitle>
            <EmptyDescription>
              A place for anything that doesn&rsquo;t need a task — just you and a blank page.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {notes.map((note) => (
            // A <button> wrapping another <button> (Delete) is invalid HTML
            // — nested interactive elements confuse both the browser's own
            // click handling and any accessibility-tree query, which is
            // exactly the ambiguity a role-based test query surfaced. The
            // Card itself carries the click (role="button", opens the
            // note); Delete stops that click reaching it via
            // stopPropagation instead of relying on DOM nesting to isolate it.
            <Card
              key={note.id}
              role="button"
              tabIndex={0}
              onClick={() => setOpenId(note.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setOpenId(note.id);
                }
              }}
              className="h-full cursor-pointer transition-colors hover:bg-accent/50"
            >
              <CardHeader>
                <CardTitle className="flex items-start justify-between gap-2">
                  <span className="min-w-0 truncate">{note.title}</span>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Delete ${note.title}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      void removeNote(note.id);
                    }}
                  >
                    <Trash2Icon />
                  </Button>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {note.body ? (
                  <p className="line-clamp-3 whitespace-pre-wrap text-sm text-muted-foreground">
                    {note.body}
                  </p>
                ) : (
                  <p className="text-sm text-muted-foreground italic">Empty</p>
                )}
                <p className="font-mono text-xs text-muted-foreground">
                  Updated {ago(note.updated_at)}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {org && openNote && (
        <NoteEditorDialog
          orgId={org.id}
          note={openNote}
          onOpenChange={(open) => !open && setOpenId(null)}
          onChanged={load}
          onDelete={() => removeNote(openNote.id)}
        />
      )}
    </>
  );
}

function NoteEditorDialog({
  orgId,
  note,
  onOpenChange,
  onChanged,
  onDelete,
}: {
  orgId: string;
  note: PersonalNote;
  onOpenChange: (open: boolean) => void;
  onChanged: () => Promise<void>;
  onDelete: () => void;
}) {
  const [title, setTitle] = useState(note.title);
  const [body, setBody] = useState(note.body);
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [savedAt, setSavedAt] = useState(note.updated_at);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // What hasn't made it to the server yet. Title and body share one debounce
  // window rather than racing two independent timers — typing in one field
  // used to reset the *other* field's pending timer without saving it,
  // which silently dropped whichever field wasn't touched last.
  const pending = useRef<{ title?: string; body?: string }>({});

  // A different note was opened — the dialog instance is the same, its
  // local state isn't, so it has to be reset explicitly. Keyed on `note.id`
  // alone, deliberately: `note.title`/`note.body` change on every autosave
  // this same dialog just triggered, and re-running this on those would
  // stomp on whatever's mid-type.
  useEffect(() => {
    setTitle(note.title);
    setBody(note.body);
    setSavedAt(note.updated_at);
    setState("idle");
    pending.current = {};
  }, [note.id]);

  const save = useCallback(
    async (fields: { title?: string; body?: string }) => {
      if ("title" in fields && !fields.title?.trim()) delete fields.title;
      if (Object.keys(fields).length === 0) return;
      setState("saving");
      try {
        const updated = await api<PersonalNote>(`/organisations/${orgId}/notes/${note.id}`, {
          method: "PATCH",
          body: JSON.stringify(fields),
        });
        setSavedAt(updated.updated_at);
        setState("saved");
        await onChanged();
      } catch {
        // Same rule PrivateNote follows: never claim a save that didn't
        // happen. The next edit retries, and the fields stay pending so
        // `flush` on close still tries once more.
        setState("idle");
        pending.current = { ...fields, ...pending.current };
      }
    },
    [orgId, note.id, onChanged],
  );

  // Cancels the debounce timer and saves whatever's still pending, right
  // now, synchronously kicking off the request rather than abandoning it.
  // Every close path — Escape, the corner X, a backdrop click — has to run
  // this, or the last few keystrokes before closing are silently lost the
  // moment the debounce timer gets cleared on unmount.
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
    setState("idle");
    pending.current = { ...pending.current, ...fields };
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(flush, AUTOSAVE_MS);
  };

  useEffect(() => () => flush(), [flush]);

  // `flush()` on unmount only covers closing the dialog *within the app* —
  // Escape, the X, a backdrop click all unmount React gracefully. A hard
  // reload or closing the tab tears down the whole JS context immediately,
  // and no unmount lifecycle runs at all, so a debounce armed but not yet
  // fired is silently lost with it. There's no way to *guarantee* the save
  // completes at that point — a PATCH can't be awaited from `beforeunload` —
  // so this is the standard fallback instead: warn before leaving while
  // something is still queued, the same prompt any editor with unsaved
  // changes shows.
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

  return (
    <Dialog open onOpenChange={onOpenChange}>
      {/* Almost full screen, not the default small centered box — a
          notepad is somewhere you actually write, and a cramped textarea
          fought that. flex-col + a flex-1 textarea is what lets the body
          claim every pixel of height the title and footer don't need,
          instead of a fixed row count. */}
      <DialogContent className="flex h-[90vh] max-h-[90vh] w-full flex-col gap-0 p-0 sm:max-w-4xl">
        {/* pr-12 reserves room for DialogContent's own corner X (absolutely
            positioned, top-2 right-2) — without it, a long title's text
            runs directly under the close button instead of stopping short
            of it. */}
        <DialogHeader className="shrink-0 border-b py-3 pr-12 pl-4">
          <DialogTitle className="sr-only">Edit note</DialogTitle>
          <DialogDescription className="sr-only">
            Edit this note&rsquo;s title and body. Changes save automatically.
          </DialogDescription>
          <Input
            aria-label="Note title"
            value={title}
            className="border-none px-0 text-xl font-semibold shadow-none focus-visible:ring-0 md:text-xl"
            onChange={(e) => {
              setTitle(e.target.value);
              queueSave({ title: e.target.value });
            }}
            onBlur={flush}
          />
        </DialogHeader>
        <Textarea
          aria-label="Note body"
          placeholder="Start typing…"
          value={body}
          className="min-h-0 flex-1 resize-none rounded-none border-none px-4 py-3 text-base shadow-none [field-sizing:fixed] focus-visible:ring-0 md:text-base"
          onChange={(e) => {
            setBody(e.target.value);
            queueSave({ body: e.target.value });
          }}
          onBlur={flush}
        />
        {/* No explicit Close button: DialogContent's own corner X already
            closes it, and there's nothing to confirm on the way out — this
            autosaves, so a second "Close" button would just be a redundant
            way to do what the X already does. */}
        <div className="flex shrink-0 items-center justify-between border-t px-4 py-3">
          <span className="text-xs text-muted-foreground">
            {state === "saving" ? "Saving…" : `Saved ${ago(savedAt)}`}
          </span>
          <Button variant="ghost" size="sm" onClick={onDelete}>
            <Trash2Icon />
            Delete
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
