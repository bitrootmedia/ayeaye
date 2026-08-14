import { BellRingIcon, CheckIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
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
  const [rows, setRows] = useState<Reminder[] | null>(null);

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
      />

      {rows.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <BellRingIcon />
            </EmptyMedia>
            <EmptyTitle>Nothing to remember</EmptyTitle>
            <EmptyDescription>
              Set one on any task and you&rsquo;ll be told the day before and on the day.
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

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border p-3">
      <span className="font-mono text-xs text-muted-foreground">{reminder.remind_on}</span>
      <span className="min-w-0 flex-1">
        {reminder.task_id && reminder.organisation_id ? (
          <Link
            to={`/orgs/${reminder.organisation_id}/tasks/${reminder.task_id}`}
            className="block truncate text-sm font-medium hover:underline"
          >
            {reminder.task_title ?? "A task"}
          </Link>
        ) : (
          <span className="block truncate text-sm font-medium">{reminder.task_title}</span>
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
      <Button size="sm" variant="outline" aria-label={`Done with ${reminder.task_title}`} onClick={done}>
        <CheckIcon />
        Done
      </Button>
      <Button
        size="sm"
        variant="ghost"
        aria-label={`Delete reminder for ${reminder.task_title}`}
        onClick={remove}
      >
        <Trash2Icon />
      </Button>
    </div>
  );
}
