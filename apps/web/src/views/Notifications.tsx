import { BellIcon, CheckCheckIcon, CheckIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "@/api";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { ago } from "@/lib/format";
import type { Notification } from "@/lib/types";

/** `YYYY-MM-DD` in the *local* timezone — `toISOString()` converts to UTC
 *  first, which slides a day near midnight for anyone not on UTC. Same
 *  reasoning as `Calendar.tsx`'s own `isoDate`. */
function localDay(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

const RECENT_LABELS = ["Today", "Yesterday", "Two days ago"];

/** Which of the four fixed buckets a notification's timestamp falls into,
 *  compared against the viewer's own local calendar day — not a 72-hour
 *  window, so 11pm yesterday and 1am today land in different buckets even
 *  though they're two hours apart. */
function bucketFor(iso: string, today: Date): string {
  const day = localDay(new Date(iso));
  for (const [offset, label] of RECENT_LABELS.entries()) {
    const d = new Date(today);
    d.setDate(d.getDate() - offset);
    if (localDay(d) === day) return label;
  }
  return "Older";
}

/** The list, already sorted newest-first by the server, split into
 *  contiguous same-bucket runs — grouping never reorders anything, it only
 *  draws a heading where the bucket changes. */
function groupByDay(items: Notification[]): { label: string; items: Notification[] }[] {
  const today = new Date();
  const groups: { label: string; items: Notification[] }[] = [];
  for (const item of items) {
    const label = bucketFor(item.created_at, today);
    const current = groups.at(-1);
    if (current?.label === label) current.items.push(item);
    else groups.push({ label, items: [item] });
  }
  return groups;
}

/**
 * The inbox.
 *
 * One per person, across every organisation — being told about a task
 * shouldn't depend on which organisation you happen to have open. Opening one
 * marks it read and takes you to the thing, because a notification you've
 * acted on shouldn't still be asking for attention.
 */
export default function Notifications() {
  const navigate = useNavigate();
  const [items, setItems] = useState<Notification[] | null>(null);

  const load = useCallback(async () => {
    setItems(await api<Notification[]>("/notifications"));
  }, []);

  useEffect(() => {
    void load().catch(() => setItems([]));
  }, [load]);

  const open = async (item: Notification) => {
    if (!item.read_at) await api(`/notifications/${item.id}/read`, { method: "POST" });
    if (item.link_path) navigate(item.link_path);
    else await load();
  };

  const markRead = async (item: Notification) => {
    await api(`/notifications/${item.id}/read`, { method: "POST" });
    await load();
  };

  const remove = async (item: Notification) => {
    // Optimistic: nothing here is worth a round trip before the row leaves
    // the list, and a failed delete just means it reappears on the next load.
    setItems((rows) => rows?.filter((r) => r.id !== item.id) ?? rows);
    await api(`/notifications/${item.id}`, { method: "DELETE" });
  };

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Notifications" }]}
        title="Notifications"
        description="What needs you, and what changed on work you're part of."
        actions={
          items && items.some((i) => !i.read_at) ? (
            <Button
              variant="ghost"
              onClick={async () => {
                await api("/notifications/read-all", { method: "POST" });
                await load();
              }}
            >
              <CheckCheckIcon />
              Mark all read
            </Button>
          ) : undefined
        }
      />

      {items === null ? (
        <div className="flex flex-1 items-center justify-center py-12">
          <Spinner />
        </div>
      ) : items.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <BellIcon />
            </EmptyMedia>
            <EmptyTitle>Nothing yet</EmptyTitle>
            <EmptyDescription>
              You&rsquo;ll hear when someone needs you on a task, hands one over, or closes
              something you were waiting on.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="space-y-4">
          {groupByDay(items).map((group) => (
            <div key={group.label}>
              <h2 className="mb-2 px-1 text-xs font-medium text-muted-foreground">
                {group.label}
              </h2>
              <div className="divide-y rounded-xl border bg-card">
                {group.items.map((item) => (
                  <NotificationRow
                    key={item.id}
                    item={item}
                    onOpen={open}
                    onMarkRead={markRead}
                    onRemove={remove}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function NotificationRow({
  item,
  onOpen,
  onMarkRead,
  onRemove,
}: {
  item: Notification;
  onOpen: (item: Notification) => void | Promise<void>;
  onMarkRead: (item: Notification) => void | Promise<void>;
  onRemove: (item: Notification) => void | Promise<void>;
}) {
  return (
    // A `<button>` can't nest the Mark-as-read/Delete buttons inside it —
    // invalid HTML, and the same trap the notepad's own card hit.
    // `role="button"` on a plain `<div>` with `tabIndex`/`onKeyDown` keeps
    // the whole row clickable and keyboard-reachable; each action button
    // stops propagation so it doesn't also fire `onOpen()`.
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(item)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          void onOpen(item);
        }
      }}
      className="flex w-full cursor-pointer items-start gap-3 p-3 text-left transition-colors hover:bg-accent/50"
    >
      {/* Unread is a dot, not a background wash: a list of highlighted
          rows is harder to scan than a list with markers on it. */}
      <span
        className={`mt-1.5 size-2 shrink-0 rounded-full ${
          item.read_at ? "bg-transparent" : "bg-primary"
        }`}
      />
      <span className="min-w-0 flex-1">
        <span className={`block text-sm ${item.read_at ? "" : "font-medium"}`}>
          {item.title}
        </span>
        {item.body && (
          // `whitespace-pre-wrap`, so the line breaks the daily digest
          // sends survive — the same as a comment or an announcement.
          // Every other body here has been one line so far, which is
          // exactly how this went unnoticed.
          <span className="block text-sm whitespace-pre-wrap text-muted-foreground">
            {item.body}
          </span>
        )}
      </span>
      <span className="shrink-0 font-mono text-xs text-muted-foreground">
        {ago(item.created_at)}
      </span>
      <span className="flex shrink-0 items-center gap-1">
        {!item.read_at && (
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Mark "${item.title}" as read`}
            onClick={(e) => {
              e.stopPropagation();
              void onMarkRead(item);
            }}
          >
            <CheckIcon />
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          aria-label={`Delete "${item.title}"`}
          onClick={(e) => {
            e.stopPropagation();
            void onRemove(item);
          }}
        >
          <Trash2Icon />
        </Button>
      </span>
    </div>
  );
}
