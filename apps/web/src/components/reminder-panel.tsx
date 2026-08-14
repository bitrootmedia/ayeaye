import { BellRingIcon, CheckIcon, PlusIcon } from "lucide-react";
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
          <div key={r.id} className="flex items-center gap-2 rounded-lg border p-2 pl-3">
            <span
              className={`font-mono text-xs ${r.overdue ? "text-status-blocker" : "text-muted-foreground"}`}
            >
              {r.remind_on}
            </span>
            <span className="min-w-0 flex-1 truncate text-sm">{r.note ?? "Reminder"}</span>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Dismiss the reminder for ${r.remind_on}`}
              onClick={() => dismiss(r)}
            >
              <CheckIcon />
            </Button>
          </div>
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
