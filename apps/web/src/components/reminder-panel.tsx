import { BellRingIcon, CheckIcon, PencilIcon, PlusIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToastManager } from "@/components/ui/toast";
import type { Reminder } from "@/lib/types";

/**
 * Reminders on one task — yours, and nobody else's.
 *
 * There is no "whose" control because there is no such thing: a reminder is a
 * note to self. Putting something in a colleague's queue is what
 * action-required does, and it already exists a card above this one.
 */
export function ReminderPanel({
  orgId,
  taskId,
  onChanged,
}: {
  orgId: string;
  taskId: string;
  /** So the rail's red badge follows without waiting for the next poll. */
  onChanged?: () => void;
}) {
  const toast = useToastManager();
  const [rows, setRows] = useState<Reminder[]>([]);
  const [when, setWhen] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const base = `/organisations/${orgId}/tasks/${taskId}/reminders`;

  const load = useCallback(async () => {
    setRows(await api<Reminder[]>(base).catch(() => []));
  }, [base]);

  useEffect(() => {
    void load();
  }, [load]);

  const add = async () => {
    if (!when || busy) return;
    setBusy(true);
    try {
      await api(base, {
        method: "POST",
        body: JSON.stringify({ remind_on: when, note: note.trim() || null }),
      });
      setWhen("");
      setNote("");
      await load();
      onChanged?.();
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "Couldn't set that reminder", description: detail });
    } finally {
      setBusy(false);
    }
  };

  const reload = async () => {
    await load();
    onChanged?.();
  };

  const dismiss = async (reminder: Reminder) => {
    await api(`/reminders/${reminder.id}`, {
      method: "PATCH",
      body: JSON.stringify({ done: true }),
    });
    await load();
    onChanged?.();
  };

  return (
    <Card role="region" aria-label="Reminders">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BellRingIcon className="size-4" />
          Reminders
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {rows.map((r) => (
          <ReminderRow key={r.id} reminder={r} onDismiss={dismiss} onSaved={reload} />
        ))}

        <div className="space-y-2">
          <Label htmlFor="remind-on">Remind me on</Label>
          <div className="flex gap-2">
            <Input
              id="remind-on"
              type="date"
              value={when}
              className="w-40"
              onChange={(e) => setWhen(e.target.value)}
            />
            <Input
              aria-label="What about"
              placeholder="What about?"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && add()}
            />
            <Button aria-label="Add reminder" disabled={!when || busy} onClick={add}>
              <PlusIcon />
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Only you see this. You&rsquo;ll be told the day before and again on the day.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * One reminder, editable in place.
 *
 * A date you can set but not move is a reminder you can only delete and
 * retype — and the endpoint has always accepted the change (`PATCH
 * /reminders/{id}`), so this was a missing control rather than a missing
 * feature. Moving the date clears the two "already notified" stamps
 * server-side, which is what makes snoozing notify again rather than going
 * quiet forever; see services/reminders.py.
 *
 * No title field here, unlike the /reminders screen: a reminder on a task
 * takes its name from the task (`ck_reminders_one_anchor`), so there is
 * nothing to edit.
 */
function ReminderRow({
  reminder,
  onDismiss,
  onSaved,
}: {
  reminder: Reminder;
  onDismiss: (reminder: Reminder) => Promise<void>;
  onSaved: () => Promise<void>;
}) {
  const toast = useToastManager();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [when, setWhen] = useState(reminder.remind_on);
  const [note, setNote] = useState(reminder.note ?? "");

  const startEditing = () => {
    // Reseeded on each open: `useState` runs once, and after a save these
    // would still hold what was typed the first time.
    setWhen(reminder.remind_on);
    setNote(reminder.note ?? "");
    setEditing(true);
  };

  const save = async () => {
    setBusy(true);
    try {
      await api(`/reminders/${reminder.id}`, {
        method: "PATCH",
        body: JSON.stringify({ remind_on: when, note }),
      });
      setEditing(false);
      await onSaved();
      toast.add({ title: "Reminder updated" });
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "Couldn't save that", description: detail });
    } finally {
      setBusy(false);
    }
  };

  if (editing) {
    return (
      <div className="space-y-2 rounded-lg border p-2 pl-3">
        <div className="flex gap-2">
          <Input
            type="date"
            aria-label={`Date for the reminder on ${reminder.remind_on}`}
            className="w-40"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
          />
          <Input
            aria-label={`Note for the reminder on ${reminder.remind_on}`}
            placeholder="What about?"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void save()}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
            Cancel
          </Button>
          <Button size="sm" disabled={busy || !when} onClick={() => void save()}>
            Save
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 rounded-lg border p-2 pl-3">
      <span
        className={`font-mono text-xs ${reminder.overdue ? "text-status-blocker" : "text-muted-foreground"}`}
      >
        {reminder.remind_on}
      </span>
      <span className="min-w-0 flex-1 truncate text-sm">{reminder.note ?? "Reminder"}</span>
      <Button
        size="sm"
        variant="ghost"
        aria-label={`Edit the reminder for ${reminder.remind_on}`}
        onClick={startEditing}
      >
        <PencilIcon />
      </Button>
      <Button
        size="sm"
        variant="ghost"
        aria-label={`Dismiss the reminder for ${reminder.remind_on}`}
        onClick={() => onDismiss(reminder)}
      >
        <CheckIcon />
      </Button>
    </div>
  );
}
