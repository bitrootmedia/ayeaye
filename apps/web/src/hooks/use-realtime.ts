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
 * Reconnects with backoff, because the interesting failure isn't the first
 * drop — it's a laptop waking from sleep to a socket that closed hours ago and
 * a page that has quietly stopped updating while looking perfectly fine.
 *
 * Events carry no content, only "conversation X moved". The handler refetches
 * over HTTP, which keeps one authorisation path for message bodies.
 */
export type RealtimeEvent = {
  type: string;
  conversation_id: string;
  message_id: string;
  anchor?: { kind: "task" | "project"; id: string };
};

const FIRST_RETRY_MS = 1_000;
const MAX_RETRY_MS = 30_000;

export function useRealtime(
  onEvent: (event: RealtimeEvent) => void,
  /**
   * What this screen currently has open.
   *
   * Announcing it is what lets someone *reading along* get live updates. The
   * server's other audience — the people it notifies — is deliberately much
   * smaller (the owner, whoever must act, people who have spoken), and a
   * read-only colleague with the thread on screen is in neither. Access is
   * checked server-side when the watch is registered.
   */
  watch?: { kind: "task" | "project"; id: string },
) {
  // Held in a ref so a changing handler doesn't tear the socket down and
  // reconnect on every render of whatever is listening.
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    let socket: WebSocket | null = null;
    const target = watch;
    let retry = FIRST_RETRY_MS;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const url = `${API_DOMAIN.replace(/^http/, "ws")}/api/ws`;

    const open = () => {
      if (closed) return;
      socket = new WebSocket(url);

      socket.onopen = () => {
        retry = FIRST_RETRY_MS;
        // Re-announced on every reconnect: a socket that came back after a
        // laptop woke up has no memory of what it was watching.
        if (target) socket?.send(JSON.stringify({ watch: target }));
      };
      socket.onmessage = (event) => {
        try {
          handler.current(JSON.parse(event.data));
        } catch {
          // A malformed frame is not worth taking the socket down for.
        }
      };
      socket.onclose = () => {
        if (closed) return;
        timer = setTimeout(open, retry);
        retry = Math.min(retry * 2, MAX_RETRY_MS);
      };
      // `onerror` is always followed by `onclose`, so reconnecting is handled
      // in one place rather than racing itself in two.
      socket.onerror = () => socket?.close();
    };

    open();
    return () => {
      closed = true;
      clearTimeout(timer);
      socket?.close();
    };
    // Reconnects when the watched thread changes — cheap, and much simpler
    // than keeping one socket and diffing subscriptions across screens.
  }, [watch?.kind, watch?.id]);
}
