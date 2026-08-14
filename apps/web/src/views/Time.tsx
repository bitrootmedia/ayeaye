import { ClockIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useOutletContext, useParams, useSearchParams } from "react-router-dom";

import { api } from "@/api";
import type { Shell } from "@/App";
import { PageHeader } from "@/components/page-header";
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
import { timestamp } from "@/lib/format";
import {
  formatDuration,
  personName,
  type RollupRow,
  type TimeEntry,
  type TimeSummary,
} from "@/lib/types";

const RANGES = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 0, label: "All time" },
];

/**
 * The work history: what was done, by whom, against what.
 *
 * Everything here is scoped to what the caller can see — the rollups aggregate
 * over the same visible-task subquery the board uses, so the totals can never
 * disagree with the tasks on screen. Two people looking at this page will
 * legitimately see different numbers, which is the point of a per-resource
 * access model rather than a bug in the arithmetic.
 */
export default function Time() {
  const { orgId } = useParams<{ orgId: string }>();
  const { organisations } = useOutletContext<Shell>();
  const [params, setParams] = useSearchParams();
  const org = organisations.find((o) => o.id === orgId) ?? null;

  const days = Number(params.get("days") ?? 7);
  const mine = params.get("mine") === "1";

  const [summary, setSummary] = useState<TimeSummary | null>(null);
  const [entries, setEntries] = useState<TimeEntry[] | null>(null);

  const load = useCallback(async () => {
    if (!orgId) return;
    const range = days ? `&days=${days}` : "";
    const [s, e] = await Promise.all([
      api<TimeSummary>(`/organisations/${orgId}/time/summary?x=1${range}`),
      api<TimeEntry[]>(`/organisations/${orgId}/time/entries?mine=${mine}${range}`),
    ]);
    setSummary(s);
    setEntries(e);
  }, [orgId, days, mine]);

  useEffect(() => {
    void load().catch(() => setEntries([]));
  }, [load]);

  if (!org) return null;

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next, { replace: true });
  };

  return (
    <>
      <PageHeader
        crumbs={[{ label: org.name, to: `/orgs/${org.id}` }, { label: "Time" }]}
        title="Time"
        description="Work logged against everything you can see."
        actions={
          <>
            {RANGES.map((r) => (
              <Button
                key={r.days}
                variant={days === r.days ? "secondary" : "ghost"}
                onClick={() => setParam("days", String(r.days))}
              >
                {r.label}
              </Button>
            ))}
            <Button
              variant={mine ? "secondary" : "ghost"}
              onClick={() => setParam("mine", mine ? "0" : "1")}
            >
              Only mine
            </Button>
          </>
        }
      />

      {summary && (
        <div className="grid gap-4 lg:grid-cols-4">
          <Card>
            <CardHeader>
              <CardTitle>Total</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="font-mono text-3xl tabular-nums">
                {formatDuration(summary.total_seconds)}
              </p>
            </CardContent>
          </Card>
          <Rollup title="By person" rows={summary.by_person} total={summary.total_seconds} />
          <Rollup title="By project" rows={summary.by_project} total={summary.total_seconds} />
          <Rollup title="By task" rows={summary.by_task} total={summary.total_seconds} />
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>History</CardTitle>
        </CardHeader>
        <CardContent>
          {entries === null ? (
            <div className="flex justify-center py-8">
              <Spinner />
            </div>
          ) : entries.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <ClockIcon />
                </EmptyMedia>
                <EmptyTitle>No time logged yet</EmptyTitle>
                <EmptyDescription>
                  Start a timer on a task, or log time you&rsquo;ve already spent.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <ul className="divide-y">
              {entries.map((entry) => (
                <li key={entry.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                  <Link
                    to={`/orgs/${org.id}/tasks/${entry.task_id}`}
                    className="min-w-0 flex-1 truncate hover:underline"
                  >
                    {entry.task_title}
                  </Link>
                  <span className="truncate text-xs text-muted-foreground">
                    {entry.project_name ?? "No project"}
                  </span>
                  <span className="truncate text-xs text-muted-foreground">
                    {personName(entry.user)}
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {timestamp(entry.started_at)}
                  </span>
                  <span className="w-16 text-right font-mono tabular-nums">
                    {entry.ended_at ? formatDuration(entry.seconds) : "running"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </>
  );
}

function Rollup({
  title,
  rows,
  total,
}: {
  title: string;
  rows: RollupRow[];
  total: number;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {rows.length === 0 && <p className="text-sm text-muted-foreground">Nothing yet.</p>}
        {rows.slice(0, 6).map((row) => (
          <div key={`${row.id}-${row.name}`} className="space-y-1">
            <div className="flex items-baseline justify-between gap-2 text-sm">
              <span className="min-w-0 truncate">{row.name}</span>
              <span className="shrink-0 font-mono text-xs tabular-nums">
                {formatDuration(row.seconds)}
              </span>
            </div>
            {/* A bar rather than a percentage: the comparison between rows is
                the whole question, and a number would have to be read twice. */}
            <div className="h-1 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary/60"
                style={{ width: `${total ? Math.round((row.seconds / total) * 100) : 0}%` }}
              />
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
