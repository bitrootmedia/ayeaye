import { LockIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { ago } from "@/lib/format";

type Note = { body: string; updated_at: string | null };

/** How long after the last keystroke to save. Long enough not to write on
 *  every letter, short enough that closing the tab doesn't lose a sentence. */
const AUTOSAVE_MS = 800;

/**
 * Your own note on a task. Nobody else can read it — ever, admins included.
 *
 * **Autosaved, with no Save button.** A note is a scratchpad; a button turns
 * it into a form you can fail to submit, and the failure mode is losing the
 * thought you were trying to keep. The trade is that the screen has to say
 * out loud when it has saved, which the timestamp does.
 *
 * The promise is enforced server-side (`services/notes.py` filters on the
 * caller in every statement). The padlock here is a description of that, not
 * an implementation of it.
 */
export function PrivateNote({ orgId, taskId }: { orgId: string; taskId: string }) {
  const [body, setBody] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  // **Not editable until the existing note has arrived.** Otherwise a fetch
  // that resolves a moment after you start typing overwrites what you typed
  // with what was on the server — which reads as the box eating a sentence,
  // and only on a slow connection.
  const [loading, setLoading] = useState(true);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setLoading(true);
    void api<Note>(`/organisations/${orgId}/tasks/${taskId}/note`)
      .then((note) => {
        setBody(note.body);
        setSaved(note.updated_at);
      })
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, [orgId, taskId]);

  const save = useCallback(
    async (next: string) => {
      setState("saving");
      try {
        const note = await api<Note>(`/organisations/${orgId}/tasks/${taskId}/note`, {
          method: "PUT",
          body: JSON.stringify({ body: next }),
        });
        setSaved(note.updated_at);
        setState("saved");
      } catch {
        // Deliberately left in "saving": the text is still in the box, and
        // claiming it saved when it didn't is the one lie a scratchpad must
        // never tell. The next keystroke retries.
        setState("idle");
      }
    },
    [orgId, taskId],
  );

  const onChange = (next: string) => {
    setBody(next);
    setState("idle");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => void save(next), AUTOSAVE_MS);
  };

  // A pending save must not be lost to navigation. Runs on unmount, which is
  // what happens when you click away to another task.
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  return (
    <Card role="region" aria-label="Private note">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <LockIcon className="size-4" />
          Private note
          <span className="ml-auto text-xs font-normal text-muted-foreground">
            {state === "saving" ? "Saving…" : saved ? `Saved ${ago(saved)}` : "Only you"}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <Textarea
          rows={4}
          value={body}
          aria-label="Your private note"
          placeholder="Notes only you can read…"
          onChange={(e) => onChange(e.target.value)}
          disabled={loading}
          onBlur={() => {
            if (timer.current) clearTimeout(timer.current);
            if (!loading) void save(body);
          }}
        />
        <p className="text-xs text-muted-foreground">
          Nobody else can see this — not the task&rsquo;s owner, not an organisation admin. It
          saves as you type, and you can find it with search.
        </p>
      </CardContent>
    </Card>
  );
}
