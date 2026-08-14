import { BellIcon, CheckCheckIcon } from "lucide-react";
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
        <div className="divide-y rounded-xl border bg-card">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => open(item)}
              className="flex w-full items-start gap-3 p-3 text-left transition-colors hover:bg-accent/50"
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
                  <span className="block text-sm text-muted-foreground">{item.body}</span>
                )}
              </span>
              <span className="shrink-0 font-mono text-xs text-muted-foreground">
                {ago(item.created_at)}
              </span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
