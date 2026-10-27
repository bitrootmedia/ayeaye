import { ChartColumnIcon, ShieldIcon, XIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useOutletContext, useParams, useSearchParams } from "react-router-dom";

import { api, ApiError } from "@/api";
import type { Shell } from "@/App";
import { EntityPicker, type PickerItem } from "@/components/entity-picker";
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
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ago, isoDate, timestamp } from "@/lib/format";
import {
  formatDuration,
  personName,
  type Member,
  type Project,
  type RightNow,
  type WorkReport,
} from "@/lib/types";
import { Rollup } from "@/views/Time";

const PRESETS = [
  { days: 1, label: "Today" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
];

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return isoDate(d);
}

/** The viewer's own zone. Every date and hour on this screen is read in it —
 *  see rule 3 in services/work_reports.py. */
const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

/**
 * Work reports: who worked on what, when, and who is on what right now.
 *
 * **Organisation admins only.** The rail only offers it to them, and the
 * server answers anyone else with a 403 — which this screen turns into a
 * sentence rather than an error, for somebody following a shared link.
 *
 * Every filter lives in the URL, like the task list, so a report somebody
 * arrived at is one they can send to a colleague. The charts are drawn from
 * the same clipped seconds as the totals, so they always add up.
 */
export default function WorkReports() {
  const { orgId } = useParams<{ orgId: string }>();
  const { organisations } = useOutletContext<Shell>();
  const [params, setParams] = useSearchParams();
  const org = organisations.find((o) => o.id === orgId) ?? null;

  const since = params.get("since") ?? daysAgo(6);
  const until = params.get("until") ?? daysAgo(0);
  const people = params.getAll("user");
  const project = params.get("project");
  const peopleKey = people.join(",");

  const [report, setReport] = useState<WorkReport | null>(null);
  const [now, setNow] = useState<RightNow[] | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState<"forbidden" | string | null>(null);

  const load = useCallback(async () => {
    if (!orgId) return;
    const query = new URLSearchParams({ since, until, tz: TZ });
    for (const id of peopleKey ? peopleKey.split(",") : []) query.append("user_id", id);
    if (project) query.set("project_id", project);
    try {
      setReport(await api<WorkReport>(`/organisations/${orgId}/reports/work?${query}`));
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) setError("forbidden");
      else if (e instanceof ApiError) setError(detailOf(e));
      else throw e;
    }
  }, [orgId, since, until, peopleKey, project]);

  const loadNow = useCallback(async () => {
    if (!orgId) return;
    try {
      setNow(await api<RightNow[]>(`/organisations/${orgId}/reports/now`));
    } catch {
      // The 403 is already said once by the report; nothing to add here.
    }
  }, [orgId]);

  useEffect(() => {
    void load();
  }, [load]);

  // "Right now" goes stale on its own, unlike a report over a fixed range.
  useEffect(() => {
    void loadNow();
    const t = window.setInterval(() => void loadNow(), 30_000);
    return () => window.clearInterval(t);
  }, [loadNow]);

  useEffect(() => {
    if (!orgId) return;
    void Promise.all([
      api<Member[]>(`/organisations/${orgId}/members`),
      api<Project[]>(`/organisations/${orgId}/projects`),
    ])
      .then(([ms, ps]) => {
        setMembers(ms);
        setProjects(ps);
      })
      .catch(() => {});
  }, [orgId]);

  const memberItems: PickerItem[] = useMemo(
    () =>
      members
        .filter((m) => m.status === "active" && m.user_id && !people.includes(m.user_id))
        .map((m) => ({
          value: m.user_id!,
          label: m.display_name || m.email || "Unknown",
          hint: m.display_name ? (m.email ?? undefined) : undefined,
        }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [members, peopleKey],
  );
  const projectItems: PickerItem[] = useMemo(
    () => projects.map((p) => ({ value: p.id, label: p.name })),
    [projects],
  );
  const nameOf = useCallback(
    (userId: string) => {
      const m = members.find((x) => x.user_id === userId);
      return m ? m.display_name || m.email || "Unknown" : "…";
    },
    [members],
  );

  if (!org) return null;

  const update = (mutate: (next: URLSearchParams) => void) => {
    const next = new URLSearchParams(params);
    mutate(next);
    setParams(next, { replace: true });
  };
  const setRange = (s: string, u: string) =>
    update((next) => {
      next.set("since", s);
      next.set("until", u);
    });

  const header = (
    <PageHeader
      crumbs={[{ label: org.name, to: `/orgs/${org.id}` }, { label: "Work reports" }]}
      title="Work reports"
      description="Who worked on what, and when. Visible to organisation admins only."
      actions={PRESETS.map((p) => {
        const active = since === daysAgo(p.days - 1) && until === daysAgo(0);
        return (
          <Button
            key={p.days}
            variant={active ? "secondary" : "ghost"}
            onClick={() => setRange(daysAgo(p.days - 1), daysAgo(0))}
          >
            {p.label}
          </Button>
        );
      })}
    />
  );

  if (error === "forbidden") {
    return (
      <>
        {header}
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <ShieldIcon />
            </EmptyMedia>
            <EmptyTitle>For organisation admins</EmptyTitle>
            <EmptyDescription>
              Work reports show everyone&rsquo;s hours, so only owners and admins of{" "}
              {org.name} can open them. Your own time is on the Time screen.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      </>
    );
  }

  const days = report?.by_day.length ?? 1;

  return (
    <>
      {header}

      {/* Filters in one row above everything they affect. */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          type="date"
          aria-label="From"
          className="w-40 font-mono"
          value={since}
          max={until}
          onChange={(e) => e.target.value && setRange(e.target.value, until)}
        />
        <span className="text-sm text-muted-foreground">to</span>
        <Input
          type="date"
          aria-label="To"
          className="w-40 font-mono"
          value={until}
          min={since}
          onChange={(e) => e.target.value && setRange(since, e.target.value)}
        />
        <div className="w-full max-w-56">
          <EntityPicker
            ariaLabel="Add a person"
            items={memberItems}
            value={null}
            placeholder={people.length ? "Add a person…" : "Everyone"}
            searchPlaceholder="Find a person…"
            emptyMessage="Nobody else to add."
            onChange={(v) => v && update((next) => next.append("user", v))}
          />
        </div>
        <div className="w-full max-w-56">
          <EntityPicker
            ariaLabel="Filter by project"
            items={projectItems}
            value={project}
            placeholder="All projects"
            emptyLabel="All projects"
            searchPlaceholder="Find a project…"
            onChange={(v) =>
              update((next) => (v ? next.set("project", v) : next.delete("project")))
            }
          />
        </div>
        {people.map((id) => (
          <Button
            key={id}
            variant="secondary"
            size="sm"
            aria-label={`Remove ${nameOf(id)}`}
            onClick={() =>
              update((next) => {
                const rest = next.getAll("user").filter((x) => x !== id);
                next.delete("user");
                for (const x of rest) next.append("user", x);
              })
            }
          >
            {nameOf(id)}
            <XIcon />
          </Button>
        ))}
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <RightNowCard orgId={org.id} rows={now} />

      {report === null ? (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Stat label="Total" value={formatDuration(report.total_seconds)} />
            <Stat
              label="Average per day"
              value={formatDuration(Math.round(report.total_seconds / days))}
            />
            <Stat label="People" value={String(report.by_person.length)} />
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <DailyChart report={report} nameOf={nameOf} />
            <HourGrid report={report} />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Rollup title="By person" rows={report.by_person} total={report.total_seconds} />
            <Rollup title="By project" rows={report.by_project} total={report.total_seconds} />
            <Rollup title="By task" rows={report.by_task} total={report.total_seconds} />
          </div>

          <EntriesCard orgId={org.id} report={report} />
        </>
      )}
    </>
  );
}

function detailOf(e: ApiError): string {
  try {
    return JSON.parse(e.body).detail ?? e.message;
  } catch {
    return e.message;
  }
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="font-mono text-3xl tabular-nums">{value}</p>
      </CardContent>
    </Card>
  );
}

/** Who is on what. A running timer is the strongest signal; an open,
 *  in-progress task they own is the next; when they last logged anything
 *  answers "is this person around at all". */
function RightNowCard({ orgId, rows }: { orgId: string; rows: RightNow[] | null }) {
  // Ticks the elapsed time between polls; the poll itself is every 30s.
  const [, setTick] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => setTick((n) => n + 1), 30_000);
    return () => window.clearInterval(t);
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Right now</CardTitle>
      </CardHeader>
      <CardContent>
        {rows === null ? (
          <div className="flex justify-center py-4">
            <Spinner />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Person</TableHead>
                <TableHead>Timing</TableHead>
                <TableHead>In progress</TableHead>
                <TableHead className="text-right">Last logged</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.user.id}>
                  <TableCell className="font-medium">{personName(r.user)}</TableCell>
                  <TableCell className="max-w-80">
                    {r.running ? (
                      <span className="flex min-w-0 items-center gap-2">
                        {/* The one live thing on the screen, so it carries the
                            primary colour rather than a status one. */}
                        <span className="size-2 shrink-0 animate-pulse rounded-full bg-primary" />
                        <Link
                          to={`/orgs/${orgId}/tasks/${r.running.task_id}`}
                          className="min-w-0 truncate hover:underline"
                        >
                          {r.running.task_title}
                        </Link>
                        <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                          {formatDuration(
                            Math.max(0, (Date.now() - Date.parse(r.running.started_at)) / 1000),
                          )}
                        </span>
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="max-w-96">
                    {r.in_progress.length === 0 ? (
                      <span className="text-muted-foreground">—</span>
                    ) : (
                      <span className="flex min-w-0 flex-wrap gap-x-3 gap-y-1">
                        {r.in_progress.slice(0, 3).map((t) => (
                          <Link
                            key={t.id}
                            to={`/orgs/${orgId}/tasks/${t.id}`}
                            className="max-w-56 truncate hover:underline"
                          >
                            {t.title}
                          </Link>
                        ))}
                        {r.in_progress.length > 3 && (
                          <span className="text-muted-foreground">
                            +{r.in_progress.length - 3}
                          </span>
                        )}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs text-muted-foreground">
                    {r.running ? "now" : r.last_active_at ? ago(r.last_active_at) : "never"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function dayLabel(iso: string, opts: Intl.DateTimeFormatOptions): string {
  // Noon, so no zone on earth slides it to the neighbouring day.
  return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, opts);
}

/** Hours per day — one series, one hue, bars anchored to the baseline. The
 *  readout above the plot names who the hovered day was made of. */
function DailyChart({
  report,
  nameOf,
}: {
  report: WorkReport;
  nameOf: (id: string) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...report.by_day.map((d) => d.seconds));
  const n = report.by_day.length;
  // Label every day up to a fortnight, then roughly every week.
  const every = n <= 14 ? 1 : Math.ceil(n / 8);
  const shown = hover === null ? null : report.by_day[hover];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Hours per day</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="h-5 truncate text-sm text-muted-foreground" aria-live="polite">
          {shown ? (
            <>
              <span className="text-foreground">
                {dayLabel(shown.date, { weekday: "short", month: "short", day: "numeric" })}
              </span>{" "}
              <span className="font-mono tabular-nums text-foreground">
                {formatDuration(shown.seconds)}
              </span>
              {shown.people.length > 0 && " · "}
              {shown.people
                .slice(0, 4)
                .map((p) => `${nameOf(p.id)} ${formatDuration(p.seconds)}`)
                .join(", ")}
            </>
          ) : (
            <>
              Peak{" "}
              <span className="font-mono tabular-nums">{formatDuration(max)}</span> in a day
            </>
          )}
        </p>
        <div
          className="flex h-40 items-end gap-0.5 border-b"
          onMouseLeave={() => setHover(null)}
        >
          {report.by_day.map((d, i) => (
            <div
              key={d.date}
              // The hit target is the full column, not the bar — a day with
              // ten minutes on it is still hoverable.
              className="flex h-full min-w-0 flex-1 items-end"
              onMouseEnter={() => setHover(i)}
              aria-label={`${d.date}: ${formatDuration(d.seconds)}`}
            >
              <div
                className={
                  hover === i
                    ? "w-full rounded-t-sm bg-primary"
                    : "w-full rounded-t-sm bg-primary/60"
                }
                style={{ height: d.seconds ? `${Math.max(2, (d.seconds / max) * 100)}%` : 0 }}
              />
            </div>
          ))}
        </div>
        <div className="flex gap-0.5">
          {report.by_day.map((d, i) => (
            <span
              key={d.date}
              className="min-w-0 flex-1 overflow-visible text-center font-mono text-[10px] whitespace-nowrap text-muted-foreground"
            >
              {i % every === 0
                ? dayLabel(d.date, n <= 7 ? { weekday: "short" } : { day: "numeric", month: "numeric" })
                : ""}
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

/** When in the week the work happens: weekday × hour, one hue, darker is
 *  more. Totals over the whole range, so a 30-day report shows the habit
 *  rather than one particular Tuesday. */
function HourGrid({ report }: { report: WorkReport }) {
  const [hover, setHover] = useState<{ d: number; h: number } | null>(null);
  const max = Math.max(1, ...report.by_hour.flat());
  const shown = hover ? report.by_hour[hover.d][hover.h] : null;

  // Sequential: one hue, mixed into the surface. The floor keeps the
  // smallest non-zero cell distinguishable from an empty one.
  const fill = (s: number) =>
    s
      ? `color-mix(in oklch, var(--primary) ${Math.round(18 + (s / max) * 82)}%, transparent)`
      : undefined;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Active hours</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="h-5 truncate text-sm text-muted-foreground" aria-live="polite">
          {hover ? (
            <>
              <span className="text-foreground">
                {WEEKDAYS[hover.d]} {String(hover.h).padStart(2, "0")}:00–
                {String((hover.h + 1) % 24).padStart(2, "0")}:00
              </span>{" "}
              <span className="font-mono tabular-nums text-foreground">
                {formatDuration(shown ?? 0)}
              </span>
            </>
          ) : (
            <>Total time in each hour of the week, {report.tz}</>
          )}
        </p>
        <div className="overflow-x-auto">
          <div
            className="grid min-w-[360px] gap-0.5"
            style={{ gridTemplateColumns: "2.5rem repeat(24, minmax(0, 1fr))" }}
            onMouseLeave={() => setHover(null)}
          >
            {report.by_hour.map((row, d) => (
              <div key={d} className="contents">
                <span className="self-center font-mono text-[10px] text-muted-foreground">
                  {WEEKDAYS[d]}
                </span>
                {row.map((s, h) => (
                  <div
                    key={h}
                    className={
                      "aspect-square rounded-[3px] " +
                      (s ? "" : "bg-muted ") +
                      (hover?.d === d && hover.h === h ? "ring-2 ring-foreground" : "")
                    }
                    style={{ background: fill(s) }}
                    onMouseEnter={() => setHover({ d, h })}
                    aria-label={`${WEEKDAYS[d]} ${h}:00, ${formatDuration(s)}`}
                  />
                ))}
              </div>
            ))}
            <span />
            {Array.from({ length: 24 }, (_, h) => (
              <span
                key={h}
                className="text-center font-mono text-[10px] text-muted-foreground"
              >
                {h % 3 === 0 ? String(h).padStart(2, "0") : ""}
              </span>
            ))}
          </div>
        </div>
        <div className="flex items-center justify-end gap-1 font-mono text-[10px] text-muted-foreground">
          less
          {[0, 0.25, 0.5, 0.75, 1].map((f) => (
            <span
              key={f}
              className={"size-3 rounded-[3px] " + (f ? "" : "bg-muted")}
              style={{ background: f ? fill(f * max) : undefined }}
            />
          ))}
          more
        </div>
      </CardContent>
    </Card>
  );
}

function EntriesCard({ orgId, report }: { orgId: string; report: WorkReport }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Entries
          {report.entries_total > report.entries.length && (
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              newest {report.entries.length} of {report.entries_total}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {report.entries.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ChartColumnIcon />
              </EmptyMedia>
              <EmptyTitle>Nothing logged in this range</EmptyTitle>
              <EmptyDescription>Try a longer range, or fewer filters.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Started</TableHead>
                <TableHead>Person</TableHead>
                <TableHead>Task</TableHead>
                <TableHead>Project</TableHead>
                <TableHead className="text-right">Duration</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report.entries.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="font-mono text-xs whitespace-nowrap">
                    {timestamp(e.started_at)}
                  </TableCell>
                  <TableCell>{personName(e.user)}</TableCell>
                  <TableCell className="max-w-80">
                    <Link
                      to={`/orgs/${orgId}/tasks/${e.task_id}`}
                      className="block truncate hover:underline"
                    >
                      {e.task_title}
                    </Link>
                    {e.note && (
                      <span className="block truncate text-xs text-muted-foreground">
                        {e.note}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {e.project_name ?? "No project"}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {e.ended_at ? formatDuration(e.seconds) : "running"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
