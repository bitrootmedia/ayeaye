/** Formatting for machine values. Every one of these is rendered in the mono
 *  face — see the type note in index.css. */

/** UUIDv7s are time-ordered, so the leading characters are the useful part. */
export function shortId(id: string): string {
  return id.slice(0, 8);
}

/** Absolute time, short. The date is dropped when it's today — on a board you
 *  compare rows against each other, and the noise isn't worth the width. */
export function timestamp(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const sameDay =
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate();
  const time = d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  if (sameDay) return time;
  const date = d.toLocaleDateString(undefined, { month: "short", day: "2-digit" });
  return `${date} ${time}`;
}

/** "4m ago" — for anywhere elapsed time is what matters more than the clock. */
export function ago(iso: string): string {
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return `${Math.floor(secs)}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}
