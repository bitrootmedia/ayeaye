import { PencilIcon, PlayIcon, PlusIcon, SquareIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToastManager } from "@/components/ui/toast";
import { timestamp } from "@/lib/format";
import {
  formatDuration,
  parseDuration,
  personName,
  type TimeEntry,
  type Timer,
} from "@/lib/types";

/**
 * Time on one task: start/stop, log what you already did, and everyone's log.
 *
 * `read` on the task is enough to log your own time — it's a record of what
 * *you* did, and refusing a contractor with view access the ability to record
 * their own hours is the wrong failure. So this panel appears for anyone who
 * can see the task; only the edit and delete controls narrow, to your own
 * entries (or anyone's, if you administer the organisation).
 */
export function TimePanel({
  orgId,
  taskId,
  meId,
  timer,
  onTimerChanged,
}: {
  orgId: string;
  taskId: string;
  meId: string | undefined;
  timer: Timer;
  onTimerChanged: () => void | Promise<void>;
}) {
  const toast = useToastManager();
  const [entries, setEntries] = useState<TimeEntry[] | null>(null);
  const [duration, setDuration] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setEntries(await api<TimeEntry[]>(`/organisations/${orgId}/tasks/${taskId}/time`));
  }, [orgId, taskId]);

  useEffect(() => {
    void load().catch(() => setEntries([]));
  }, [load]);

  const runningHere = timer.entry?.task_id === taskId;
  const total = (entries ?? []).reduce((sum, e) => sum + e.seconds, 0);

  const act = async (fn: () => Promise<unknown>, success?: string) => {
    setBusy(true);
    try {
      await fn();
      await load();
      await onTimerChanged();
      if (success) toast.add({ title: success });
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "That didn't work", description: detail });
    } finally {
      setBusy(false);
    }
  };

  const startOrStop = () =>
    act(async () => {
      if (runningHere) {
        await api("/me/timer/stop", { method: "POST" });
        return;
      }
      const res = await api<{ stopped: TimeEntry | null }>(
        `/organisations/${orgId}/tasks/${taskId}/time/start`,
        { method: "POST" },
      );
      // Starting stops whatever was running. Saying so out loud beats
      // silently pausing the clock on something else.
      if (res.stopped) {
        toast.add({
          title: "Timer switched",
          description: `Stopped your timer on “${res.stopped.task_title ?? "another task"}”.`,
        });
      }
    });

  const logManual = () => {
    const minutes = parseDuration(duration);
    if (!minutes) {
      toast.add({
        title: "Couldn't read that",
        description: "Try 45, 90m, 1h30 or 1.5h.",
      });
      return;
    }
    return act(async () => {
      await api(`/organisations/${orgId}/tasks/${taskId}/time`, {
        method: "POST",
        body: JSON.stringify({ minutes }),
      });
      setDuration("");
    }, `Logged ${formatDuration(minutes * 60)}`);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2">
          <span>Time</span>
          {total > 0 && (
            <span className="font-mono text-sm font-normal text-muted-foreground">
              {formatDuration(total)}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Button
          variant={runningHere ? "outline" : "default"}
          className="w-full"
          disabled={busy}
          onClick={startOrStop}
        >
          {runningHere ? <SquareIcon className="fill-current" /> : <PlayIcon />}
          {runningHere ? "Stop timer" : "Start timer"}
        </Button>

        <div className="space-y-2">
          <Label htmlFor="log-time">Log time already spent</Label>
          <div className="flex gap-2">
            <Input
              id="log-time"
              value={duration}
              placeholder="1h30"
              onChange={(e) => setDuration(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && logManual()}
            />
            <Button variant="outline" disabled={busy || !duration.trim()} onClick={logManual}>
              <PlusIcon />
              Log
            </Button>
          </div>
          {/* People type durations a dozen ways; say which ones work rather
              than rejecting four of them silently. */}
          <p className="text-xs text-muted-foreground">45, 90m, 1h30 or 1.5h all work.</p>
        </div>

        {entries && entries.length > 0 && (
          <ul className="space-y-2 border-t pt-3">
            {entries.map((entry) => (
              <EntryRow
                key={entry.id}
                orgId={orgId}
                entry={entry}
                mine={entry.user?.id === meId}
                onChanged={() => act(async () => {})}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function EntryRow({
  orgId,
  entry,
  mine,
  onChanged,
}: {
  orgId: string;
  entry: TimeEntry;
  mine: boolean;
  onChanged: () => void;
}) {
  const toast = useToastManager();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(String(Math.round(entry.seconds / 60)));

  const save = async () => {
    const minutes = parseDuration(value);
    if (!minutes) {
      toast.add({ title: "Couldn't read that", description: "Try 45, 90m or 1h30." });
      return;
    }
    try {
      await api(`/organisations/${orgId}/time/${entry.id}`, {
        method: "PATCH",
        body: JSON.stringify({ minutes }),
      });
      setEditing(false);
      onChanged();
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "Couldn't change that", description: detail });
    }
  };

  return (
    <li className="flex items-center gap-2 text-sm">
      <span className="min-w-0 flex-1">
        <span className="truncate">{personName(entry.user)}</span>
        <span className="block font-mono text-xs text-muted-foreground">
          {timestamp(entry.started_at)}
          {/* Corrections are visible rather than silent — the whole reason
              entries stay editable is that the numbers should be right AND
              honest about having changed. */}
          {entry.edited_at && " · edited"}
        </span>
      </span>

      {editing ? (
        <>
          <Input
            value={value}
            aria-label="Duration"
            className="h-7 w-20"
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
          />
          {/* Named distinctly from the task's own Save: two controls with the
              same accessible name on one screen is ambiguous for a screen
              reader as much as for a test. */}
          <Button size="sm" variant="ghost" aria-label="Save duration" onClick={save}>
            Save
          </Button>
        </>
      ) : (
        <>
          {entry.ended_at === null ? (
            <Badge variant="outline" className="gap-1.5 text-primary">
              <span className="size-1.5 rounded-full bg-primary" />
              running
            </Badge>
          ) : (
            <span className="font-mono tabular-nums">{formatDuration(entry.seconds)}</span>
          )}
          {/* Shown only where they'd work: your own entries, or anyone's if
              you administer the organisation — in which case the API allows it
              and these simply appear. */}
          {mine && entry.ended_at && (
            <>
              <Button
                size="sm"
                variant="ghost"
                aria-label="Edit duration"
                onClick={() => setEditing(true)}
              >
                <PencilIcon />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label="Remove entry"
                onClick={async () => {
                  await api(`/organisations/${orgId}/time/${entry.id}`, { method: "DELETE" });
                  onChanged();
                }}
              >
                <Trash2Icon />
              </Button>
            </>
          )}
        </>
      )}
    </li>
  );
}
