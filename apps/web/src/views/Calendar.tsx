import {
  BellIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  PlaneIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useOutletContext, useParams, useSearchParams } from "react-router-dom";

import { api } from "@/api";
import type { Shell } from "@/App";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  PRIORITY_TONE,
  STATUS_DOT,
  personName,
  type CalendarAbsence,
  type CalendarData,
  type CalendarReminder,
  type CalendarTask,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** `YYYY-MM-DD` in the *local* timezone — `toISOString()` converts to UTC
 *  first, which slides a day near midnight for anyone not on UTC. Every date
 *  here is a plain calendar day, not an instant, the same reasoning
 *  `services/reminders.py` gives for doing this arithmetic itself rather
 *  than trusting a library. */
function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** The Monday on or before the 1st of the month — where a 6-week grid
 *  starts so every day of the month has a cell, Monday-first. */
function gridStart(year: number, month: number): Date {
  const first = new Date(year, month, 1);
  const mondayIndex = (first.getDay() + 6) % 7; // Sun=0 -> 6, Mon=1 -> 0, ...
  const start = new Date(year, month, 1 - mondayIndex);
  start.setHours(0, 0, 0, 0);
  return start;
}

/**
 * Every visible task's due date, and your own reminders, on one month grid.
 *
 * **Tasks and out-of-office are team-wide, reminders are yours alone** — see
 * the endpoint's own docstring for why that split is deliberate rather than
 * inconsistent. A shared "what's due when" only works if it shows the whole
 * team's work, and OOO is the one thing on this grid that is *not* private by
 * product decision (services/presence.py): its whole value is a colleague
 * checking before they ask you for something. A reminder is a note to
 * yourself, and there is no version of the product where somebody else's
 * private note appears on your screen.
 *
 * Hand-rolled, not a calendar library: a month grid is a CSS grid and some
 * date arithmetic, and this product reaches for a dependency only once
 * hand-rolling it stops being simple — see `@dnd-kit` in the Planner for
 * what that threshold looks like. Click-through only, no drag-and-drop, so
 * it never crossed it.
 */
export default function CalendarView() {
  const { orgId } = useParams<{ orgId: string }>();
  const { organisations } = useOutletContext<Shell>();
  const [params, setParams] = useSearchParams();
  const org = organisations.find((o) => o.id === orgId) ?? null;

  const today = useMemo(() => new Date(), []);
  // In the URL, same reasoning as every other view/filter in this product: a
  // month somebody navigated to is one they can send a colleague.
  const monthParam = params.get("month");
  const [year, month] = useMemo(() => {
    if (monthParam && /^\d{4}-\d{2}$/.test(monthParam)) {
      const [y, m] = monthParam.split("-").map(Number);
      return [y, m - 1];
    }
    return [today.getFullYear(), today.getMonth()];
  }, [monthParam, today]);

  const [data, setData] = useState<CalendarData | null>(null);

  const start = useMemo(() => gridStart(year, month), [year, month]);
  const days = useMemo(
    () => Array.from({ length: 42 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)),
    [start],
  );
  const end = days[41];

  const load = useCallback(async () => {
    if (!orgId) return;
    setData(null);
    setData(
      await api<CalendarData>(
        `/organisations/${orgId}/calendar?start=${isoDate(start)}&end=${isoDate(end)}`,
      ).catch(() => ({ tasks: [], reminders: [], away: [] })),
    );
  }, [orgId, start, end]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!org) return null;

  const byDay = new Map<
    string,
    { tasks: CalendarTask[]; reminders: CalendarReminder[]; away: CalendarAbsence[] }
  >();
  for (const day of days) byDay.set(isoDate(day), { tasks: [], reminders: [], away: [] });
  for (const t of data?.tasks ?? []) byDay.get(t.due_on)?.tasks.push(t);
  for (const r of data?.reminders ?? []) byDay.get(r.remind_on)?.reminders.push(r);
  // Unlike a task or reminder's single date, an absence spans a range, so it
  // has to be checked against every day in the grid rather than looked up by
  // one key.
  for (const a of data?.away ?? []) {
    for (const day of days) {
      const iso = isoDate(day);
      if (iso >= a.starts_on && iso <= a.ends_on) byDay.get(iso)?.away.push(a);
    }
  }

  const goTo = (y: number, m: number) => {
    const normalised = new Date(y, m, 1);
    setParams(
      { month: `${normalised.getFullYear()}-${String(normalised.getMonth() + 1).padStart(2, "0")}` },
      { replace: true },
    );
  };
  const monthLabel = new Date(year, month, 1).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
  const todayIso = isoDate(today);

  return (
    <>
      <PageHeader
        crumbs={[{ label: org.name, to: `/orgs/${org.id}` }, { label: "Calendar" }]}
        title="Calendar"
        description="Every visible task's due date, your own reminders, and who's away."
        actions={
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              aria-label="Previous month"
              onClick={() => goTo(year, month - 1)}
            >
              <ChevronLeftIcon />
            </Button>
            <Button variant="ghost" onClick={() => goTo(today.getFullYear(), today.getMonth())}>
              Today
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Next month"
              onClick={() => goTo(year, month + 1)}
            >
              <ChevronRightIcon />
            </Button>
            <span className="ml-2 min-w-36 font-medium">{monthLabel}</span>
          </div>
        }
      />

      {data === null ? (
        <div className="flex flex-1 items-center justify-center py-12">
          <Spinner />
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border">
          <div className="grid grid-cols-7 border-b bg-muted/40 text-xs font-medium text-muted-foreground">
            {WEEKDAYS.map((w) => (
              <div key={w} className="px-2 py-1.5">
                {w}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-7">
            {days.map((day) => {
              const iso = isoDate(day);
              const cell = byDay.get(iso) ?? { tasks: [], reminders: [], away: [] };
              const inMonth = day.getMonth() === month;
              const isToday = iso === todayIso;
              const items = [...cell.tasks, ...cell.reminders, ...cell.away];
              const shown = items.slice(0, 3);
              const overflow = items.length - shown.length;
              return (
                <div
                  key={iso}
                  className={cn(
                    "min-h-28 space-y-1 border-r border-b p-1.5 last:border-r-0",
                    !inMonth && "bg-muted/20",
                  )}
                >
                  <span
                    className={cn(
                      "inline-flex size-6 items-center justify-center rounded-full text-xs",
                      !inMonth && "text-muted-foreground",
                      isToday && "bg-primary font-medium text-primary-foreground",
                    )}
                  >
                    {day.getDate()}
                  </span>
                  <div className="space-y-1">
                    {shown.map((item) =>
                      "due_on" in item ? (
                        <TaskChip key={`t-${item.id}`} orgId={org.id} task={item} />
                      ) : "remind_on" in item ? (
                        <ReminderChip key={`r-${item.id}`} orgId={org.id} reminder={item} />
                      ) : (
                        <AbsenceChip key={`a-${item.id}`} absence={item} />
                      ),
                    )}
                    {overflow > 0 && (
                      <p className="px-1 text-xs text-muted-foreground">+{overflow} more</p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
}

function TaskChip({ orgId, task }: { orgId: string; task: CalendarTask }) {
  return (
    <Link
      to={`/orgs/${orgId}/tasks/${task.id}`}
      title={task.title}
      className="flex items-center gap-1 truncate rounded px-1 py-0.5 text-xs hover:bg-accent"
    >
      <span className={cn("size-1.5 shrink-0 rounded-full", STATUS_DOT[task.status])} />
      <span className={cn("truncate", PRIORITY_TONE[task.priority])}>{task.title}</span>
    </Link>
  );
}

function AbsenceChip({ absence }: { absence: CalendarAbsence }) {
  const label = personName(absence.person);
  return (
    <div
      title={absence.note ? `${label} — ${absence.note}` : label}
      className="flex items-center gap-1 truncate rounded px-1 py-0.5 text-xs text-muted-foreground"
    >
      <PlaneIcon className="size-3 shrink-0" />
      <span className="truncate">{label}</span>
    </div>
  );
}

function ReminderChip({ orgId, reminder }: { orgId: string; reminder: CalendarReminder }) {
  return (
    <Link
      to={`/orgs/${orgId}/tasks/${reminder.task_id}`}
      title={reminder.note || reminder.task_title}
      className="flex items-center gap-1 truncate rounded px-1 py-0.5 text-xs text-muted-foreground hover:bg-accent"
    >
      <BellIcon className="size-3 shrink-0" />
      <span className="truncate">{reminder.note || reminder.task_title}</span>
    </Link>
  );
}
