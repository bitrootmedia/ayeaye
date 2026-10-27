import {
  ArrowRightIcon,
  CheckIcon,
  ClockIcon,
  ListTodoIcon,
  MessageSquareQuoteIcon,
  PlaneIcon,
  TimerIcon,
  UserIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router-dom";

import { ApiError, api } from "@/api";
import type { Shell } from "@/App";
import { PageHeader } from "@/components/page-header";
import { PriorityGlyph } from "@/components/priority";
import { RoleBadge } from "@/components/role-badge";
import { StatusBadge } from "@/components/status-badge";
import { WorkingHoursGrid } from "@/components/working-hours-grid";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { ago } from "@/lib/format";
import { personName, type MemberProfile as Profile, type ProfileTask } from "@/lib/types";
import { convertWeek, hoursUntilWorking, wallClock } from "@/lib/working-hours";

/**
 * One colleague, for the question you ask before getting in touch: is now a
 * good time, and what are they on?
 *
 * Everything here is something you could already reach elsewhere —
 * out-of-office from the dashboard, their tasks from the task list — and
 * each keeps that rule. Working hours used to be a dialog on the roster;
 * this replaced it. In particular their work
 * is only what *your* task access reaches, so a colleague on a private
 * project simply shows fewer tasks; the screen says "that you can see"
 * rather than implying it's everything. See `services/profiles.py`.
 */
export default function MemberProfile() {
  const { orgId, userId } = useParams<{ orgId: string; userId: string }>();
  const { organisations, me } = useOutletContext<Shell>();
  const org = organisations.find((o) => o.id === orgId) ?? null;

  const [profile, setProfile] = useState<Profile | null | "missing">(null);

  useEffect(() => {
    if (!orgId || !userId) return;
    api<Profile>(`/organisations/${orgId}/members/${userId}/profile`)
      .then(setProfile)
      .catch((err) =>
        setProfile(err instanceof ApiError && err.status === 404 ? "missing" : null),
      );
  }, [orgId, userId]);

  if (!org) return null;
  if (profile === "missing") {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <UserIcon />
          </EmptyMedia>
          <EmptyTitle>Nobody by that link here</EmptyTitle>
          <EmptyDescription>
            They may have left {org.name}, or the link is for another organisation.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button render={<Link to={`/orgs/${org.id}/people`} />} nativeButton={false}>
            People
          </Button>
        </EmptyContent>
      </Empty>
    );
  }
  if (profile === null) {
    return (
      <div className="flex flex-1 items-center justify-center py-12">
        <Spinner />
      </div>
    );
  }

  const name = personName(profile);
  const isMe = profile.id === me?.id;

  return (
    <>
      <PageHeader
        crumbs={[
          { label: "Organisations", to: "/" },
          { label: org.name, to: `/orgs/${org.id}` },
          { label: "People", to: `/orgs/${org.id}/people` },
          { label: name },
        ]}
        title={isMe ? `${name} (you)` : name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            {profile.display_name && <span className="font-mono text-xs">{profile.email}</span>}
            <RoleBadge role={profile.role} />
            {profile.joined_at && (
              <span className="text-xs">
                joined {new Date(profile.joined_at).toLocaleDateString()}
              </span>
            )}
          </span>
        }
        actions={
          isMe && (
            <Button variant="outline" render={<Link to="/account" />} nativeButton={false}>
              Edit on your account
            </Button>
          )
        }
      />

      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        <RightNow profile={profile} />
        <WorkingOn profile={profile} orgId={org.id} />
      </div>

      <TasksCard
        label="Open tasks"
        icon={<ListTodoIcon className="size-4" />}
        tasks={profile.open_tasks}
        orgId={org.id}
        empty={`Nothing open of ${isMe ? "yours" : "theirs"} that you can see.`}
        footer={
          profile.open_total > profile.open_tasks.length && (
            <p className="text-xs text-muted-foreground">
              {profile.open_tasks.length} of{" "}
              <span className="font-mono">{profile.open_total}</span> you can see, most recently
              updated first.{" "}
              <Link
                className="underline underline-offset-2"
                to={`/orgs/${org.id}/tasks?owner=${profile.id}`}
              >
                Tasks they own
              </Link>
            </p>
          )
        }
      />
      {profile.recently_closed.length > 0 && (
        <TasksCard
          label="Recently closed"
          icon={<CheckIcon className="size-4" />}
          tasks={profile.recently_closed}
          orgId={org.id}
          closed
        />
      )}

      <WorkingHoursCard profile={profile} myTimezone={me?.timezone ?? null} />
    </>
  );
}

/** Their local time, whether that's inside their hours, and whether they're
 *  away — the three things that decide "message now or later". Ticks every
 *  minute, so a tab left open doesn't keep claiming it's 9am. */
function RightNow({ profile }: { profile: Profile }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  const tz = profile.timezone;
  const clock = tz ? wallClock(tz, now) : null;
  const time = tz
    ? new Intl.DateTimeFormat(undefined, {
        timeZone: tz,
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
      }).format(now)
    : null;
  const until = clock ? hoursUntilWorking(profile.working_hours, clock) : null;
  const awayNow = profile.away.filter((a) => a.away_now);
  const awaySoon = profile.away.filter((a) => !a.away_now);

  return (
    <Card role="region" aria-label="Right now">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ClockIcon className="size-4" />
          Right now
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {time ? (
          <p>
            <span className="font-mono text-lg tabular-nums">{time}</span>{" "}
            <span className="text-xs text-muted-foreground">their time ({tz})</span>
          </p>
        ) : (
          <p className="text-muted-foreground">No timezone on record yet.</p>
        )}

        {/* Shape, not colour: red and amber belong to status. */}
        {profile.working_hours.length === 0 ? (
          <p className="text-muted-foreground">No working hours recorded.</p>
        ) : until === 0 ? (
          <p className="flex items-center gap-2">
            <CheckIcon className="size-4" />
            Within their working hours
          </p>
        ) : until !== null ? (
          <p className="flex items-center gap-2 text-muted-foreground">
            <ClockIcon className="size-4" />
            Outside their working hours — back in{" "}
            <span className="font-mono">{until}h</span>
          </p>
        ) : null}

        {awayNow.map((a) => (
          <p key={a.id} className="flex flex-wrap items-center gap-2">
            <PlaneIcon className="size-4" />
            Away until <span className="font-mono">{a.ends_on}</span>
            {a.note && <span className="text-muted-foreground">— {a.note}</span>}
          </p>
        ))}

        {profile.status_message && (
          <p className="flex items-start gap-2">
            <MessageSquareQuoteIcon className="mt-0.5 size-4 shrink-0" />
            <span className="whitespace-pre-wrap">{profile.status_message}</span>
          </p>
        )}

        {awaySoon.length > 0 && (
          <div className="space-y-1 border-t pt-3">
            <p className="text-xs font-medium text-muted-foreground">Away soon</p>
            {awaySoon.map((a) => (
              <p key={a.id} className="flex flex-wrap items-baseline gap-2">
                <span className="font-mono text-xs">
                  {a.starts_on} → {a.ends_on}
                </span>
                {a.note && <span className="text-xs text-muted-foreground">{a.note}</span>}
              </p>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** Their running timer — reported only when it's on a task you can see, so
 *  "nothing you can see" is the honest empty state, not "idle". */
function WorkingOn({ profile, orgId }: { profile: Profile; orgId: string }) {
  const on = profile.working_on;
  return (
    <Card role="region" aria-label="Working on">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <TimerIcon className="size-4" />
          Working on
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {on ? (
          <>
            <TaskRow task={on.task} orgId={orgId} />
            <p className="text-xs text-muted-foreground">
              Timer running since{" "}
              <span className="font-mono">
                {new Date(on.started_at).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>{" "}
              ({ago(on.started_at)})
            </p>
          </>
        ) : (
          <p className="text-muted-foreground">No timer running on anything you can see.</p>
        )}
      </CardContent>
    </Card>
  );
}

function TasksCard({
  label,
  icon,
  tasks,
  orgId,
  empty,
  footer,
  closed,
}: {
  label: string;
  icon: React.ReactNode;
  tasks: ProfileTask[];
  orgId: string;
  empty?: string;
  footer?: React.ReactNode;
  closed?: boolean;
}) {
  return (
    <Card role="region" aria-label={label} className="mb-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {icon}
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {tasks.length === 0 && empty && (
          <p className="text-sm text-muted-foreground">{empty}</p>
        )}
        {tasks.map((t) => (
          <TaskRow key={t.id} task={t} orgId={orgId} closed={closed} />
        ))}
        {footer}
      </CardContent>
    </Card>
  );
}

function TaskRow({
  task,
  orgId,
  closed,
}: {
  task: ProfileTask;
  orgId: string;
  closed?: boolean;
}) {
  return (
    <Link
      to={`/orgs/${orgId}/tasks/${task.id}`}
      className="flex flex-wrap items-center gap-2 rounded-lg border p-3 text-sm hover:bg-accent/50"
    >
      <PriorityGlyph priority={task.priority} />
      <span className="min-w-0 flex-1 truncate font-medium">{task.title}</span>
      <StatusBadge status={task.status} />
      {task.project_name && (
        <span className="truncate text-xs text-muted-foreground">{task.project_name}</span>
      )}
      {task.is_action_required && (
        <Badge variant="outline" className="gap-1.5">
          <ArrowRightIcon className="size-3" />
          Their action
        </Badge>
      )}
      <span className="font-mono text-xs text-muted-foreground">
        {closed && task.closed_at ? `closed ${ago(task.closed_at)}` : ago(task.updated_at)}
      </span>
    </Link>
  );
}

function WorkingHoursCard({
  profile,
  myTimezone,
}: {
  profile: Profile;
  myTimezone: string | null;
}) {
  // Only worth a second, converted grid when both timezones are known and
  // actually differ — nothing honest to convert to otherwise.
  const converted =
    profile.timezone && myTimezone && profile.timezone !== myTimezone
      ? convertWeek(profile.working_hours, profile.timezone, myTimezone)
      : null;
  return (
    <Card role="region" aria-label="Working hours" className="mb-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ClockIcon className="size-4" />
          Working hours
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-muted-foreground">
          {profile.timezone
            ? `Recorded in ${profile.timezone}.`
            : "No timezone on record — shown as entered."}
        </p>
        <WorkingHoursGrid cells={profile.working_hours} />
        {profile.working_hours.length === 0 && (
          <p className="text-sm text-muted-foreground">Nothing recorded yet.</p>
        )}
        {converted && (
          <div className="space-y-1 border-t pt-3">
            <p className="text-xs font-medium text-muted-foreground">
              In your timezone ({myTimezone})
            </p>
            <WorkingHoursGrid cells={converted} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
