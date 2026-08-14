import { SquareIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api";
import { Button } from "@/components/ui/button";
import { formatClock, type Timer } from "@/lib/types";

/**
 * The running timer, in the header, on every screen.
 *
 * **The clock ticks locally.** The server is asked once (and again on a slow
 * poll); the displayed value is computed from `started_at` against the
 * browser's own clock. Polling per second would be a request per second per
 * open tab to render a number that is entirely predictable — and a clock that
 * only moves when the network does looks broken.
 *
 * It shows wherever the timer is running, **including another organisation**.
 * There is one timer per person across the whole installation, and the failure
 * this prevents is finding one still running tomorrow because you switched
 * organisations and it fell out of view.
 */
export function TimerBar({ timer, onChanged }: { timer: Timer; onChanged: () => void }) {
  const entry = timer.entry;
  const [elapsed, setElapsed] = useState(0);
  const [stopping, setStopping] = useState(false);

  useEffect(() => {
    if (!entry) return;
    const started = new Date(entry.started_at).getTime();
    // Trust the server's own measurement for the offset, then keep time
    // locally: it stays right even if the two clocks disagree.
    const drift = Date.now() - started - entry.seconds * 1000;
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - started - drift) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [entry]);

  if (!entry) return null;

  const stop = async () => {
    setStopping(true);
    try {
      await api("/me/timer/stop", { method: "POST" });
      onChanged();
    } finally {
      setStopping(false);
    }
  };

  const href = timer.organisation_id
    ? `/orgs/${timer.organisation_id}/tasks/${entry.task_id}`
    : null;

  return (
    // role=status, not a bare div: it is a live region announcing ongoing
    // state, and it gives the thing a name to be found by rather than a
    // position in the DOM.
    <div
      role="status"
      aria-label="Running timer"
      className="flex items-center gap-2 rounded-md border border-primary/30 bg-primary/5 py-1 pr-1 pl-2.5"
    >
      {/* A pulsing dot, not a spinner: it means "still going", not "loading". */}
      <span className="relative flex size-2 shrink-0">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-60" />
        <span className="relative inline-flex size-2 rounded-full bg-primary" />
      </span>
      <span aria-label="Elapsed" className="font-mono text-sm tabular-nums">
        {formatClock(elapsed)}
      </span>
      {href ? (
        <Link to={href} className="hidden max-w-40 truncate text-xs text-muted-foreground md:block">
          {entry.task_title}
        </Link>
      ) : (
        <span className="hidden max-w-40 truncate text-xs text-muted-foreground md:block">
          {entry.task_title}
        </span>
      )}
      <Button variant="ghost" size="sm" onClick={stop} disabled={stopping} aria-label="Stop the running timer">
        <SquareIcon className="fill-current" />
      </Button>
    </div>
  );
}
