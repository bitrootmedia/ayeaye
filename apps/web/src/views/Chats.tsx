import {
  BellOffIcon,
  BookmarkIcon,
  FolderKanbanIcon,
  MessageCirclePlusIcon,
  MessagesSquareIcon,
  PaperclipIcon,
  PinIcon,
  SearchIcon,
  UsersIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router-dom";

import { ApiError, api, apiWithHeaders } from "@/api";
import type { Shell } from "@/App";
import { ChatConversation } from "@/components/chat-conversation";
import { EntityPicker } from "@/components/entity-picker";
import { PeoplePicker } from "@/components/people-picker";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { useToastManager } from "@/components/ui/toast";
import { useRealtime } from "@/hooks/use-realtime";
import {
  CHAT_FILTERS,
  CHAT_FILTER_LABEL,
  STATUS_DOT,
  personName,
  type ChatFilter,
  type ChatOut,
  type Member,
  type Person,
  type Presence,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { lastView, rememberView } from "@/lib/view-preference";

const PAGE = 50;
/** Live events arrive in bursts — a message, then its read cursor, then
 *  somebody else's reply. One refetch per burst, not one per event. */
const COALESCE_MS = 300;
/** A green dot is worth a request a minute, not more: it is a hint about
 *  whether to expect a quick answer, not a guarantee. */
const PRESENCE_MS = 60_000;
const SEARCH_DEBOUNCE_MS = 250;

/** Telegram's rule for the time beside a chat: the clock today, the weekday
 *  this week, a date before that. */
function listTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  if (now.getTime() - d.getTime() < 6 * 86_400_000) {
    return d.toLocaleDateString(undefined, { weekday: "short" });
  }
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function initials(name: string): string {
  const parts = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase();
}

/**
 * Chats: every conversation you're in, in one list, Telegram-shaped.
 *
 * **One list, not one per kind.** DMs, groups, and the comment threads on
 * tasks and projects you have a stake in all sit together, newest first —
 * which is what makes "where was that conversation?" answerable without
 * remembering which task it happened on. The server decides what's in it
 * (see `services/chats.py`); filters only narrow.
 *
 * Two panes on a wide screen, one at a time on a narrow one: the list at
 * `/chats`, the conversation at `/chats/:id` with a back button. The
 * conversation component mounts once either way — it owns a realtime watch,
 * and two live copies would double it.
 */
export default function Chats() {
  const { orgId, chatId } = useParams<{ orgId: string; chatId?: string }>();
  const { organisations, me, refreshUnread } = useOutletContext<Shell>();
  const org = organisations.find((o) => o.id === orgId) ?? null;
  const navigate = useNavigate();
  const toast = useToastManager();

  const [filter, setFilter] = useState<ChatFilter>(() => {
    const saved = lastView("chat-filter");
    return CHAT_FILTERS.includes(saved as ChatFilter) && saved !== "archived"
      ? (saved as ChatFilter)
      : "all";
  });
  const [query, setQuery] = useState("");
  const [q, setQ] = useState("");
  const [chats, setChats] = useState<ChatOut[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [people, setPeople] = useState<Person[]>([]);
  const [presence, setPresence] = useState<Map<string, Presence>>(new Map());
  const [starting, setStarting] = useState<"direct" | "group" | null>(null);

  // How many rows are on screen, so a live refetch reloads all of them rather
  // than collapsing a list somebody scrolled to the bottom of back to one page.
  const loaded = useRef(PAGE);

  useEffect(() => {
    const t = setTimeout(() => setQ(query.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [query]);

  const listUrl = useCallback(
    (limit: number, offset: number) => {
      const params = new URLSearchParams({ filter, limit: String(limit), offset: String(offset) });
      if (q) params.set("q", q);
      return `/organisations/${orgId}/chats?${params}`;
    },
    [orgId, filter, q],
  );

  const load = useCallback(async () => {
    if (!orgId) return;
    try {
      const { data, headers } = await apiWithHeaders<ChatOut[]>(
        listUrl(Math.max(PAGE, loaded.current), 0),
      );
      setChats(data);
      setTotal(Number(headers.get("X-Total-Count") ?? data.length));
    } catch {
      setChats((current) => current ?? []);
    }
  }, [orgId, listUrl]);

  useEffect(() => {
    loaded.current = PAGE;
    setChats(null);
    void load();
  }, [load]);

  const loadMore = async () => {
    if (!chats || loadingMore || chats.length >= total) return;
    setLoadingMore(true);
    try {
      const { data, headers } = await apiWithHeaders<ChatOut[]>(listUrl(PAGE, chats.length));
      const seen = new Set(chats.map((c) => c.id));
      const next = [...chats, ...data.filter((c) => !seen.has(c.id))];
      loaded.current = next.length;
      setChats(next);
      setTotal(Number(headers.get("X-Total-Count") ?? next.length));
    } finally {
      setLoadingMore(false);
    }
  };

  // Everybody you could start a chat with: the organisation's active members.
  useEffect(() => {
    if (!orgId) return;
    void api<Member[]>(`/organisations/${orgId}/members`)
      .then((members) =>
        setPeople(
          members
            .filter((m) => m.status === "active" && m.user_id)
            .map((m) => ({ id: m.user_id!, email: m.email, display_name: m.display_name })),
        ),
      )
      .catch(() => setPeople([]));
  }, [orgId]);

  const loadPresence = useCallback(async () => {
    if (!orgId) return;
    try {
      const rows = await api<Presence[]>(`/organisations/${orgId}/presence`);
      setPresence(new Map(rows.map((p) => [p.user_id, p])));
    } catch {
      // A missed poll leaves the last answer up; the next one tries again.
    }
  }, [orgId]);

  useEffect(() => {
    void loadPresence();
    const id = setInterval(loadPresence, PRESENCE_MS);
    return () => clearInterval(id);
  }, [loadPresence]);

  // The list and the rail's badge after something moved — coalesced, since
  // a conversation going back and forth is a burst of events.
  const pending = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const changed = useCallback(() => {
    clearTimeout(pending.current);
    pending.current = setTimeout(() => {
      void load();
      refreshUnread();
    }, COALESCE_MS);
  }, [load, refreshUnread]);
  useEffect(() => () => clearTimeout(pending.current), []);

  useRealtime(
    useCallback(
      (event) => {
        if (event.type !== "message") return;
        if (event.organisation_id && event.organisation_id !== orgId) return;
        changed();
      },
      [orgId, changed],
    ),
  );

  const startDirect = async (userId: string) => {
    try {
      const chat = await api<ChatOut>(`/organisations/${orgId}/chats/direct`, {
        method: "POST",
        body: JSON.stringify({ user_id: userId }),
      });
      setStarting(null);
      changed();
      navigate(`/orgs/${orgId}/chats/${chat.id}`);
    } catch (err) {
      toast.add({
        title: "Couldn't open that chat",
        description: err instanceof ApiError ? err.body : undefined,
      });
    }
  };

  const startGroup = async (title: string, userIds: string[]) => {
    try {
      const chat = await api<ChatOut>(`/organisations/${orgId}/chats/groups`, {
        method: "POST",
        body: JSON.stringify({ title, user_ids: userIds }),
      });
      setStarting(null);
      changed();
      navigate(`/orgs/${orgId}/chats/${chat.id}`);
    } catch (err) {
      toast.add({
        title: "Couldn't create that group",
        description: err instanceof ApiError ? err.body : undefined,
      });
    }
  };

  if (!org || !orgId) return null;

  return (
    // Edge to edge under the shell's header: a messenger is the screen, not a
    // card on it. The negative margin undoes `main`'s padding, and the height
    // is what's left under the 4rem header.
    <div className="-m-4 flex h-[calc(100dvh-4rem)] min-h-0 md:-m-6">
      {/* The list */}
      <aside
        className={cn(
          "flex min-h-0 w-full flex-col border-r md:w-80 md:shrink-0 lg:w-96",
          chatId && "hidden md:flex",
        )}
        aria-label="Chats"
      >
        <div className="space-y-2 border-b p-3">
          <div className="flex items-center gap-2">
            <h1 className="flex-1 text-base font-semibold">Chats</h1>
            <Button
              size="sm"
              variant="outline"
              aria-label="New group"
              onClick={() => setStarting("group")}
            >
              <UsersIcon />
              <span className="hidden sm:inline">New group</span>
            </Button>
            <Button size="sm" onClick={() => setStarting("direct")}>
              <MessageCirclePlusIcon />
              New message
            </Button>
          </div>
          <div className="relative">
            <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search chats and messages"
              aria-label="Search chats"
              className="pl-8"
            />
          </div>
          {/* Wraps rather than scrolls: a sideways-scrolling strip hid
              "Archived" off the edge at the list's usual width. */}
          <div className="-mx-1 flex flex-wrap gap-1" role="tablist">
            {CHAT_FILTERS.map((f) => (
              <button
                key={f}
                type="button"
                role="tab"
                aria-selected={filter === f}
                onClick={() => {
                  setFilter(f);
                  // Archived is somewhere you visit, not a view to come back to.
                  if (f !== "archived") rememberView("chat-filter", f);
                }}
                className={cn(
                  "shrink-0 rounded-full px-2.5 py-1 text-xs transition-colors",
                  filter === f
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent",
                )}
              >
                {CHAT_FILTER_LABEL[f]}
              </button>
            ))}
          </div>
        </div>
        <div
          className="min-h-0 flex-1 overflow-y-auto"
          onScroll={(e) => {
            const el = e.currentTarget;
            if (el.scrollHeight - el.scrollTop - el.clientHeight < 200) void loadMore();
          }}
        >
          {chats === null ? (
            <div className="flex justify-center py-8">
              <Spinner />
            </div>
          ) : chats.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">
              {q
                ? `Nothing matches “${q}”.`
                : filter === "all"
                  ? "No conversations yet. Start one, or comment on a task — its thread shows up here."
                  : `Nothing under ${CHAT_FILTER_LABEL[filter]}.`}
            </p>
          ) : (
            <ul>
              {chats.map((chat) => (
                <ChatRow
                  key={chat.id}
                  chat={chat}
                  orgId={orgId}
                  me={me?.id}
                  active={chat.id === chatId}
                  presence={presence}
                />
              ))}
              {loadingMore && (
                <li className="flex justify-center py-3">
                  <Spinner />
                </li>
              )}
            </ul>
          )}
        </div>
      </aside>

      {/* The conversation */}
      <section
        className={cn("min-h-0 min-w-0 flex-1 flex-col", chatId ? "flex" : "hidden md:flex")}
        aria-label="Conversation"
      >
        {chatId ? (
          <ChatConversation
            key={chatId}
            orgId={orgId}
            chatId={chatId}
            me={me?.id}
            people={people}
            presence={presence}
            onChanged={changed}
            onBack={() => navigate(`/orgs/${orgId}/chats`)}
          />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
            <MessagesSquareIcon className="size-8" />
            Choose a chat, or start a new one.
          </div>
        )}
      </section>

      <NewDirectDialog
        open={starting === "direct"}
        onOpenChange={(open) => setStarting(open ? "direct" : null)}
        people={people}
        me={me?.id}
        onPick={startDirect}
      />
      <NewGroupDialog
        open={starting === "group"}
        onOpenChange={(open) => setStarting(open ? "group" : null)}
        people={people}
        me={me?.id}
        onCreate={startGroup}
      />
    </div>
  );
}

function ChatRow({
  chat,
  orgId,
  me,
  active,
  presence,
}: {
  chat: ChatOut;
  orgId: string;
  me: string | undefined;
  active: boolean;
  presence: Map<string, Presence>;
}) {
  const other = chat.kind === "direct" ? chat.members.find((m) => m.id !== me) : undefined;
  const online = other ? (presence.get(other.id) ?? other).online : false;
  const saved = chat.kind === "direct" && !other;
  const last = chat.last_message;

  // What precedes the preview: "You:" for your own, the author's name in a
  // group or a thread, nothing in a DM where it can only be the other person.
  const who = !last
    ? ""
    : last.mine
      ? "You: "
      : chat.kind !== "direct" && last.author
        ? `${personName(last.author)}: `
        : "";

  return (
    <li>
      <Link
        to={`/orgs/${orgId}/chats/${chat.id}`}
        aria-current={active ? "page" : undefined}
        className={cn(
          "flex items-center gap-3 px-3 py-2.5 transition-colors hover:bg-accent/50",
          active && "bg-accent",
        )}
      >
        <div className="relative shrink-0">
          <div className="flex size-10 items-center justify-center rounded-full bg-muted text-sm font-medium text-muted-foreground">
            {chat.kind === "task" && chat.task ? (
              // Status owns the colour scale, so the task's own dot is the
              // avatar: a blocked task's thread looks blocked from the list.
              <span className={cn("size-3 rounded-full", STATUS_DOT[chat.task.status])} />
            ) : chat.kind === "project" ? (
              <FolderKanbanIcon className="size-4" />
            ) : chat.kind === "group" ? (
              <UsersIcon className="size-4" />
            ) : saved ? (
              <BookmarkIcon className="size-4" />
            ) : (
              initials(chat.title)
            )}
          </div>
          {online && (
            // The accent, not a status colour: status owns the only scale,
            // and "online" is about a person, not the state of any work.
            <span
              className="absolute right-0 bottom-0 size-3 rounded-full border-2 border-background bg-primary"
              aria-label="online"
            />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                "truncate text-sm",
                chat.unread > 0 ? "font-semibold" : "font-medium",
                chat.task?.closed && "text-muted-foreground line-through",
              )}
            >
              {chat.title}
            </span>
            {chat.muted && <BellOffIcon className="size-3 shrink-0 text-muted-foreground" />}
            <span className="ml-auto shrink-0 font-mono text-xs text-muted-foreground">
              {chat.last_message_at && listTime(chat.last_message_at)}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
              {!last ? (
                <span className="italic">No messages yet</span>
              ) : last.deleted ? (
                <span className="italic">{who}Message deleted</span>
              ) : (
                <>
                  {who}
                  {last.attachments > 0 && (
                    <PaperclipIcon className="mr-0.5 inline size-3 align-[-2px]" />
                  )}
                  {/* A message that is only files has no words to preview. */}
                  {last.body || (last.attachments > 1 ? `${last.attachments} files` : "File")}
                </>
              )}
            </span>
            {chat.pinned && chat.unread === 0 && (
              <PinIcon className="size-3 shrink-0 text-muted-foreground" aria-label="Pinned" />
            )}
            {chat.unread > 0 && (
              <span
                className={cn(
                  "min-w-5 shrink-0 rounded-full px-1.5 text-center font-mono text-[11px] leading-5",
                  // A muted chat still counts, but greyed: it's there if you
                  // look, and it doesn't ask for you.
                  chat.muted ? "bg-muted text-muted-foreground" : "bg-primary text-primary-foreground",
                )}
              >
                {chat.unread}
              </span>
            )}
          </div>
        </div>
      </Link>
    </li>
  );
}

function NewDirectDialog({
  open,
  onOpenChange,
  people,
  me,
  onPick,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  people: Person[];
  me: string | undefined;
  onPick: (userId: string) => void;
}) {
  // Yourself first, as "Saved messages" — a DM with yourself is the
  // scratchpad Telegram people already reach for.
  const items = useMemo(
    () => [
      ...(me ? [{ value: me, label: "Saved messages", hint: "Notes to yourself" }] : []),
      ...people
        .filter((p) => p.id !== me)
        .sort((a, b) => personName(a).localeCompare(personName(b)))
        .map((p) => ({
          value: p.id,
          label: personName(p),
          hint: p.display_name ? (p.email ?? undefined) : undefined,
        })),
    ],
    [people, me],
  );
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New message</DialogTitle>
          <DialogDescription>
            A direct message is private to the two of you — organisation admins can't read it.
          </DialogDescription>
        </DialogHeader>
        <EntityPicker
          ariaLabel="Who to message"
          items={items}
          value={null}
          placeholder="Choose a person…"
          searchPlaceholder="Find a person…"
          onChange={(v) => v && onPick(v)}
        />
      </DialogContent>
    </Dialog>
  );
}

function NewGroupDialog({
  open,
  onOpenChange,
  people,
  me,
  onCreate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  people: Person[];
  me: string | undefined;
  onCreate: (title: string, userIds: string[]) => void;
}) {
  const [title, setTitle] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  useEffect(() => {
    if (open) {
      setTitle("");
      setSelected([]);
    }
  }, [open]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New group</DialogTitle>
          <DialogDescription>
            Only the people in it can read it — admins included only if they're added.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="group-title">Name</Label>
          <Input
            id="group-title"
            value={title}
            maxLength={120}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Lunch club"
          />
        </div>
        <PeoplePicker
          people={people}
          selected={selected}
          onChange={setSelected}
          exclude={me ? [me] : []}
        />
        <DialogFooter>
          <Button disabled={!title.trim()} onClick={() => onCreate(title.trim(), selected)}>
            Create group
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
