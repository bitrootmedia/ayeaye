import type { WorkingHourCell } from "@/lib/types";

export const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const HOURS = Array.from({ length: 24 }, (_, h) => h);

export function cellKey(weekday: number, hour: number): string {
  return `${weekday}-${hour}`;
}

export function cellSet(cells: WorkingHourCell[]): Set<string> {
  return new Set(cells.map((c) => cellKey(c.weekday, c.hour)));
}

/** A timezone's offset from UTC, in minutes, at a given instant. There is no
 *  built-in `getTimezoneOffset(timeZone)` — only the browser's own local zone
 *  exposes that directly — so this round-trips through `Intl.DateTimeFormat`:
 *  read `at` back as if it were UTC wall-clock time in `timeZone`, and the gap
 *  between that reading and `at` itself is the offset. */
function offsetMinutes(timeZone: string, at: Date): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(at);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  const asUtc = Date.UTC(
    get("year"),
    get("month") - 1,
    get("day"),
    get("hour") % 24,
    get("minute"),
    get("second"),
  );
  return Math.round((asUtc - at.getTime()) / 60_000);
}

/** Shifts a weekly grid from one IANA timezone to another, rounded to the
 *  nearest hour — the grid itself has no finer resolution, so a half-hour
 *  offset zone (India, Nepal, …) is necessarily approximate here, the same
 *  kind of documented simplification the calendar's own hand-rolled date
 *  math already accepts elsewhere in this product. Uses *today's* offset for
 *  both zones rather than the offset on whatever day each cell nominally
 *  falls on, so the grid never shows two different shifts for cells either
 *  side of a DST transition it happens to straddle. */
export function convertWeek(
  cells: WorkingHourCell[],
  fromTz: string,
  toTz: string,
): WorkingHourCell[] {
  const now = new Date();
  const diffHours = Math.round((offsetMinutes(toTz, now) - offsetMinutes(fromTz, now)) / 60);
  if (diffHours === 0) return cells;
  return cells.map(({ weekday, hour }) => {
    const total = ((weekday * 24 + hour + diffHours) % 168) + 168; // avoid a negative modulo
    const wrapped = total % 168;
    return { weekday: Math.floor(wrapped / 24), hour: wrapped % 24 };
  });
}
