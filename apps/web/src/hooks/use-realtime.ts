import { useEffect, useRef } from "react";

import { API_DOMAIN } from "@/config";

/**
 * The realtime socket.
 *
 * **Authenticated by the session cookie**, which single origin gives us for
 * free: the SPA, the API and this socket share a host, so the browser sends
 * the cookie with the upgrade. No token in a query string, where it would land
 * in server logs and browser history.
 *
 * **One socket per tab, shared between subscribers.** The task screen has two
 * of them — the comment thread and the task itself — and a connection each
 * would mean two upgrades, two watch registrations and two reconnect loops for
 * one page. Subscribers are refcounted here; the socket opens with the first
 * and closes with the last.
 *
 * Reconnects with backoff, because the interesting failure isn't the first
 * drop — it's a laptop waking from sleep to a socket that closed hours ago and
 * a page that has quietly stopped updating while looking perfectly fine.
 *
 * Events carry no content, only "this thing moved". The handler refetches over
 * HTTP, which keeps one authorisation path for the data itself — and means a
 * viewer whose access was just revoked gets a 404 rather than a payload.
 */
export type RealtimeEvent = {
  /** "message" for a comment, "task" for anything else about a task. */
  type: string;
  conversation_id?: string;
  message_id?: string;
  /** Set on `type: "task"`. */
  task_id?: string;
  /** What moved, for debugging — never branch on it: a screen that only
   *  refreshes for changes it recognises stops refreshing the day somebody
   *  adds a sixth kind. */
  change?: string;
  anchor?: { kind: "task" | "project"; id: string };
  organisation_id?: string;
};

/** `org` is the board: it shows many tasks at once, so watching each of them
 *  would be hundreds of registrations per tab. Membership is the check. */
export type Watch = { kind: "task" | "project" | "org"; id: string };

const FIRST_RETRY_MS = 1_000;
const MAX_RETRY_MS = 30_000;

type Subscriber = { onEvent: (event: RealtimeEvent) => void; watch?: Watch };

/**
 * How long the socket lingers after the last subscriber goes.
 *
 * **Not a micro-optimisation — without it the socket churns.** React mounts
 * and unmounts effects around a render (twice over in StrictMode), and the
 * two subscribers on a task screen arrive at different times because the
 * comment thread only mounts once the task has loaded. Closing on the exact
 * moment the count hits zero meant three connections per page open, and an
 * event landing in that window was simply lost — which showed up as a change
 * that reached the other tab most of the time.
 */
const LINGER_MS = 250;

const subscribers = new Set<Subscriber>();
let socket: WebSocket | null = null;
let retry = FIRST_RETRY_MS;
let timer: ReturnType<typeof setTimeout> | undefined;
let closing: ReturnType<typeof setTimeout> | undefined;

/**
 * What the one socket should be watching.
 *
 * The server allows a socket **one** watch at a time — opening a task replaces
 * whatever came before, so a long session doesn't accumulate every thread
 * you've visited. On a task screen both subscribers want the same key, so
 * taking the last one registered is right; on a project screen only the thread
 * asks for anything.
 */
function currentWatch(): Watch | undefined {
  let latest: Watch | undefined;
  for (const sub of subscribers) if (sub.watch) latest = sub.watch;
  return latest;
}

function announceWatch() {
  const watch = currentWatch();
  if (watch && socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ watch }));
  }
}

function open() {
  if (socket || subscribers.size === 0) return;
  const ws = new WebSocket(`${API_DOMAIN.replace(/^http/, "ws")}/api/ws`);
  socket = ws;

  ws.onopen = () => {
    retry = FIRST_RETRY_MS;
    // Re-announced on every reconnect: a socket that came back after a laptop
    // woke up has no memory of what it was watching.
    announceWatch();
  };
  ws.onmessage = (event) => {
    let parsed: RealtimeEvent;
    try {
      parsed = JSON.parse(event.data);
    } catch {
      return; // A malformed frame is not worth taking the socket down for.
    }
    // A copy, because a handler may unsubscribe while we're iterating.
    for (const sub of [...subscribers]) sub.onEvent(parsed);
  };
  ws.onclose = () => {
    socket = null;
    if (subscribers.size === 0) return;
    timer = setTimeout(open, retry);
    retry = Math.min(retry * 2, MAX_RETRY_MS);
  };
  // `onerror` is always followed by `onclose`, so reconnecting is handled in
  // one place rather than racing itself in two.
  ws.onerror = () => ws.close();
}

export function useRealtime(onEvent: (event: RealtimeEvent) => void, watch?: Watch) {
  // Held in a ref so a changing handler doesn't churn the subscription on
  // every render of whatever is listening.
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    const sub: Subscriber = {
      onEvent: (event) => handler.current(event),
      watch,
    };
    subscribers.add(sub);
    // A close was pending from the previous screen — this is that screen's
    // successor, so keep the connection.
    clearTimeout(closing);
    open();
    announceWatch();

    return () => {
      subscribers.delete(sub);
      if (subscribers.size > 0) {
        // Someone else is still listening, and the watch may have been ours.
        announceWatch();
        return;
      }
      clearTimeout(closing);
      closing = setTimeout(() => {
        if (subscribers.size > 0) return; // Somebody came back.
        clearTimeout(timer);
        const ws = socket;
        socket = null;
        ws?.close();
      }, LINGER_MS);
    };
    // Re-registers when the watched thing changes. No reconnect needed now
    // that the socket is shared — just another `watch` frame.
  }, [watch?.kind, watch?.id]);
}
