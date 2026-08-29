import { BellRingIcon, CheckIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";

import { ApiError, api } from "@/api";
import type { Shell } from "@/App";
import { EntityPicker, type PickerItem } from "@/components/entity-picker";
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
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { useToastManager } from "@/components/ui/toast";
import { lastOrg } from "@/lib/current-org";
import type { Reminder } from "@/lib/types";

/**
 * Every reminder you have, across organisations.
 *
 * Cross-organisation for the same reason the inbox is: you don't want to find
 * out you missed something by switching organisation. Due and upcoming are
 * separated rather than sorted together, because "what have I let slip" and
 * "what's coming" are two different questions and only one of them is urgent.
 */
export default function Reminders() {
  const { organisations } = useOutletContext<Shell>();
  const [rows, setRows] = useState<Reminder[] | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    setRows(await api<Reminder[]>("/reminders").catch(() => []));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (rows === null) {
    return (
      <div className="flex flex-1 items-center justify-center py-12">
        <Spinner />
      </div>
    );
  }

  const due = rows.filter((r) => r.overdue);
  const upcoming = rows.filter((r) => !r.overdue);

  return (
    <>
      <PageHeader
        title="Reminders"
        description="Yours alone — nobody else can see these, and nobody else is told."
        actions={
          organisations.length > 0 && (
            <Button onClick={() => setAdding(true)}>
              <PlusIcon />
              New reminder
            </Button>
          )
        }
      />

      {rows.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <BellRingIcon />
            </EmptyMedia>
            <EmptyTitle>Nothing to remember</EmptyTitle>
            <EmptyDescription>
              Set one on any task, or on nothing in particular, and you&rsquo;ll be told the day
              before and on the day.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="space-y-4">
          {due.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <span className="size-2 rounded-full bg-status-blocker" />
                  Due now
                  <span className="font-mono text-sm font-normal text-muted-foreground">
                    {due.length}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {due.map((r) => (
                  <Row key={r.id} reminder={r} onChanged={load} />
                ))}
              </CardContent>
            </Card>
          )}

          {upcoming.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Coming up</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {upcoming.map((r) => (
                  <Row key={r.id} reminder={r} onChanged={load} />
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      )}

      <NewReminderDialog
        open={adding}
        onOpenChange={setAdding}
        organisations={organisations}
        onCreated={load}
      />
    </>
  );
}

function Row({ reminder, onChanged }: { reminder: Reminder; onChanged: () => Promise<void> }) {
  const done = async () => {
    await api(`/reminders/${reminder.id}`, { method: "PATCH", body: JSON.stringify({ done: true }) });
    await onChanged();
  };
  const remove = async () => {
    await api(`/reminders/${reminder.id}`, { method: "DELETE" });
    await onChanged();
  };

  // Exactly one of the two is ever set — a task-anchored reminder has no
  // `title` column value, a standalone one has no task (ck_reminders_one_anchor).
  const label = reminder.task_title ?? reminder.title ?? "Reminder";

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border p-3">
      <span className="font-mono text-xs text-muted-foreground">{reminder.remind_on}</span>
      <span className="min-w-0 flex-1">
        {reminder.task_id && reminder.organisation_id ? (
          <Link
            to={`/orgs/${reminder.organisation_id}/tasks/${reminder.task_id}`}
            className="block truncate text-sm font-medium hover:underline"
          >
            {label}
          </Link>
        ) : (
          <span className="block truncate text-sm font-medium">{label}</span>
        )}
        {reminder.note && (
          <span className="block truncate text-xs text-muted-foreground">{reminder.note}</span>
        )}
      </span>
      {reminder.organisation_name && (
        <Badge variant="outline" className="font-normal">
          {reminder.organisation_name}
        </Badge>
      )}
      {/* Dismissing is the point: a reminder you can see but not silence is an
          alarm with no off switch, and the badge would stay red forever. */}
      <Button size="sm" variant="outline" aria-label={`Done with ${label}`} onClick={done}>
        <CheckIcon />
        Done
      </Button>
      <Button size="sm" variant="ghost" aria-label={`Delete reminder for ${label}`} onClick={remove}>
        <Trash2Icon />
      </Button>
    </div>
  );
}

function NewReminderDialog({
  open,
  onOpenChange,
  organisations,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  organisations: Shell["organisations"];
  onCreated: () => Promise<void>;
}) {
  const toast = useToastManager();
  const [title, setTitle] = useState("");
  const [when, setWhen] = useState("");
  const [note, setNote] = useState("");
  const [orgId, setOrgId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    const last = lastOrg();
    setOrgId(
      (last && organisations.some((o) => o.id === last) ? last : organisations[0]?.id) ?? null,
    );
  }, [open, organisations]);

  const orgItems: PickerItem[] = organisations.map((o) => ({ value: o.id, label: o.name }));

  const reset = () => {
    setTitle("");
    setWhen("");
    setNote("");
  };

  const submit = async () => {
    if (!title.trim() || !when || !orgId || busy) return;
    setBusy(true);
    try {
      await api(`/organisations/${orgId}/reminders`, {
        method: "POST",
        body: JSON.stringify({ remind_on: when, title: title.trim(), note: note.trim() || null }),
      });
      reset();
      onOpenChange(false);
      await onCreated();
      toast.add({ title: "Reminder set" });
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "Couldn't set that reminder", description: detail });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New reminder</DialogTitle>
          <DialogDescription>
            About nothing in particular — no task needed. Only you see this.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="reminder-title">What about</Label>
            <Input
              id="reminder-title"
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="reminder-when">Remind me on</Label>
              <Input
                id="reminder-when"
                type="date"
                value={when}
                onChange={(e) => setWhen(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="reminder-org">Organisation</Label>
              <EntityPicker
                id="reminder-org"
                ariaLabel="Organisation"
                items={orgItems}
                value={orgId}
                searchPlaceholder="Find an organisation…"
                onChange={setOrgId}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="reminder-note">Note</Label>
            <Input id="reminder-note" value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
          <Button onClick={submit} disabled={busy || !title.trim() || !when || !orgId}>
            Set reminder
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
