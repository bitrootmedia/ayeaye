import {
  ArchiveIcon,
  ArchiveRestoreIcon,
  ArrowLeftIcon,
  BellIcon,
  BellOffIcon,
  BookmarkIcon,
  ExternalLinkIcon,
  FileIcon,
  FolderKanbanIcon,
  LogOutIcon,
  MoreVerticalIcon,
  PaperclipIcon,
  PencilIcon,
  PinIcon,
  PinOffIcon,
  ReplyIcon,
  SendIcon,
  Trash2Icon,
  UserPlusIcon,
  UsersIcon,
  XIcon,
} from "lucide-react";
import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, api } from "@/api";
import { Lightbox } from "@/components/lightbox";
import {
  MentionTextarea,
  MentionedText,
  type MentionPerson,
} from "@/components/mention-textarea";
import { PeoplePicker } from "@/components/people-picker";
import { PriorityGlyph } from "@/components/priority";
import { StatusBadge } from "@/components/status-badge";
import { VoiceNotePlayer, VoiceNoteRecorder } from "@/components/voice-note";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useToastManager } from "@/components/ui/toast";
import { useFileDrop } from "@/hooks/use-file-drop";
import { useRealtime, type Watch } from "@/hooks/use-realtime";
import { ago } from "@/lib/format";
import { canRecord } from "@/lib/audio";
import { formatBytes, isAudio, isImage, putToStorage } from "@/lib/storage";
import {
  personName,
  type ChatAttachment,
  type ChatMessage,
  type ChatOut,
  type ChatPage,
  type Person,
  type Presence,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type Ticket = { attachment: ChatAttachment; upload_url: string; content_type: string };

/** A page is fifty: enough to fill a tall screen, small enough that opening a
 *  chat with years in it is one quick request. Older ones come on scroll. */
const PAGE = 50;
/** Consecutive messages from one person within this long read as one block —
 *  a name and a time once, not on every line. */
const GROUP_MS = 5 * 60_000;
/** How close to the bottom still counts as "reading the latest", so a new
 *  message follows you down rather than appearing off-screen. */
const STICKY_PX = 120;

/** UUIDv7 ids sort as strings in time order, so merging pages is a sort by id
 *  with no dates to parse. */
function merge(current: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  const byId = new Map(current.map((m) => [m.id, m]));
  for (const m of incoming) byId.set(m.id, m);
  return [...byId.values()].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

function errorDetail(err: unknown, fallback = "Try again."): string {
  if (!(err instanceof ApiError)) return fallback;
  try {
    return (JSON.parse(err.body).detail as string) ?? fallback;
  } catch {
    return fallback;
  }
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: d.getFullYear() === today.getFullYear() ? undefined : "numeric",
  });
}

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/** "online", or "last seen 4m ago" — the line under a DM's name. */
export function seenLine(p: { online: boolean; last_seen_at: string | null } | undefined) {
  if (!p) return null;
  if (p.online) return "online";
  return p.last_seen_at ? `last seen ${ago(p.last_seen_at)}` : "offline";
}

/**
 * One conversation, Telegram-shaped: bubbles, newest at the bottom, older
 * pages on scroll up, a composer pinned underneath.
 *
 * **Any kind of conversation** — a DM, a group, or a task's or project's
 * comments — because they are one system server-side: posting into a task
 * thread here *is* commenting on the task. What differs is only the header
 * (a task links to itself, a DM shows whether the other person is around)
 * and who can be @-named.
 *
 * Keyed on the conversation by its parent, so switching chats is a fresh
 * component — no half-typed draft or reply carried from one chat to the
 * next, the same lesson the detail screens' `Keyed` route wrapper learned.
 */
export function ChatConversation({
  orgId,
  chatId,
  me,
  people,
  presence,
  onChanged,
  onBack,
}: {
  orgId: string;
  chatId: string;
  me: string | undefined;
  /** The organisation's active members, for adding people to a group. */
  people: Person[];
  /** Polled by the page; overrides what the chat's own fetch said, which is
   *  as old as the last time the chat was loaded. */
  presence: Map<string, Presence>;
  /** The list and the rail's badge should look again — something was read,
   *  sent, renamed or left. */
  onChanged: () => void;
  /** Narrow screens show one pane at a time; this is the way back to the list. */
  onBack: () => void;
}) {
  const toast = useToastManager();
  const navigate = useNavigate();
  const base = `/organisations/${orgId}/chats/${chatId}`;

  const [chat, setChat] = useState<ChatOut | null | "missing">(null);
  const [messages, setMessages] = useState<ChatMessage[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [canPost, setCanPost] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [mentionable, setMentionable] = useState<MentionPerson[]>([]);

  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [replyTo, setReplyTo] = useState<ChatMessage | null>(null);
  const [staged, setStaged] = useState<ChatAttachment[]>([]);
  const [uploading, setUploading] = useState<{ name: string; pct: number } | null>(null);

  const [renaming, setRenaming] = useState<string | null>(null);
  const [adding, setAdding] = useState<string[] | null>(null);
  const [leaving, setLeaving] = useState(false);

  const scroller = useRef<HTMLDivElement>(null);
  const filePicker = useRef<HTMLInputElement>(null);
  // The composer's wrapper, not the textarea: `MentionTextarea` owns its own
  // ref to the box for the caret maths, and a second ref passed in would
  // replace it.
  const composer = useRef<HTMLDivElement>(null);
  // What the next layout pass should do with the scroll position: follow to
  // the bottom (first load, a message you sent, one that arrived while you
  // were at the bottom) or hold still while older messages land above.
  const scrollIntent = useRef<{ kind: "bottom" } | { kind: "keep"; fromBottom: number } | null>(
    null,
  );
  const readUpto = useRef<string | null>(null);

  const loadChat = useCallback(async () => {
    try {
      setChat(await api<ChatOut>(base));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setChat("missing");
    }
  }, [base]);

  const atBottom = () => {
    const el = scroller.current;
    return !el || el.scrollHeight - el.scrollTop - el.clientHeight < STICKY_PX;
  };

  /** The newest page, merged over whatever older pages are already loaded —
   *  so a live update never throws away the history you scrolled up for. */
  const loadNewest = useCallback(
    async (follow?: boolean) => {
      try {
        const page = await api<ChatPage>(`${base}/messages?limit=${PAGE}`);
        if (follow ?? atBottom()) scrollIntent.current = { kind: "bottom" };
        setMessages((current) => {
          if (current === null) {
            setHasMore(page.has_more);
            return page.messages;
          }
          // A message removed or edited is in the newest page as its new
          // self; anything newer than the oldest of this page that is no
          // longer here can't happen — messages are never hard-deleted.
          return merge(current, page.messages);
        });
        setCanPost(page.can_post);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) setChat("missing");
      }
    },
    [base],
  );

  const loadOlder = useCallback(async () => {
    if (!messages?.length || !hasMore || loadingOlder) return;
    setLoadingOlder(true);
    try {
      const page = await api<ChatPage>(`${base}/messages?limit=${PAGE}&before=${messages[0].id}`);
      const el = scroller.current;
      if (el) scrollIntent.current = { kind: "keep", fromBottom: el.scrollHeight - el.scrollTop };
      setMessages((current) => merge(current ?? [], page.messages));
      setHasMore(page.has_more);
    } finally {
      setLoadingOlder(false);
    }
  }, [base, messages, hasMore, loadingOlder]);

  useEffect(() => {
    void loadChat();
    void loadNewest(true);
  }, [loadChat, loadNewest]);

  useLayoutEffect(() => {
    const el = scroller.current;
    const intent = scrollIntent.current;
    if (!el || !intent) return;
    scrollIntent.current = null;
    if (intent.kind === "bottom") el.scrollTop = el.scrollHeight;
    else el.scrollTop = el.scrollHeight - intent.fromBottom;
  }, [messages]);

  // Who can be @-named: a chat's members, or for a task thread everybody who
  // can see the task (the same endpoint the task's own comments use). A
  // project thread has no such list — see `services/mentions.py`.
  const kind = chat && chat !== "missing" ? chat.kind : null;
  const taskId = chat && chat !== "missing" ? chat.task?.id : undefined;
  const memberKey =
    chat && chat !== "missing" ? chat.members.map((m) => m.id).join(",") : "";
  useEffect(() => {
    if (!chat || chat === "missing") return;
    if (chat.kind === "direct" || chat.kind === "group") {
      setMentionable(
        chat.members
          .filter((m) => m.id !== me)
          .map((m) => ({
            id: m.id,
            name: m.display_name || m.email || "",
            hint: m.display_name ? (m.email ?? undefined) : undefined,
          }))
          .filter((p) => p.name),
      );
      return;
    }
    if (chat.kind !== "task" || !taskId) return setMentionable([]);
    let live = true;
    void api<Person[]>(`/organisations/${orgId}/tasks/${taskId}/mentionable`)
      .then((list) => {
        if (!live) return;
        setMentionable(
          list
            .map((p) => ({
              id: p.id,
              name: p.display_name || p.email || "",
              hint: p.display_name ? (p.email ?? undefined) : undefined,
            }))
            .filter((p) => p.name),
        );
      })
      .catch(() => setMentionable([]));
    return () => {
      live = false;
    };
    // `memberKey` stands in for the members array, which is a new object on
    // every refetch even when nobody came or went.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, taskId, memberKey, orgId, me]);

  /** Mark read up to the newest message — but only while you can actually
   *  see it. A chat left open in a background tab must not swallow the
   *  unread badge for messages nobody has looked at. */
  const markRead = useCallback(() => {
    const last = messages?.at(-1);
    if (!last || readUpto.current === last.id) return;
    if (document.visibilityState !== "visible" || !document.hasFocus()) return;
    readUpto.current = last.id;
    void api(`${base}/read`, { method: "POST", body: JSON.stringify({ message_id: last.id }) })
      .then(onChanged)
      .catch(() => {
        readUpto.current = null;
      });
  }, [messages, base, onChanged]);

  useEffect(() => {
    markRead();
    window.addEventListener("focus", markRead);
    document.addEventListener("visibilitychange", markRead);
    return () => {
      window.removeEventListener("focus", markRead);
      document.removeEventListener("visibilitychange", markRead);
    };
  }, [markRead]);

  // What to watch, so the open chat moves while it's on screen even for a
  // reader with no stake: a DM or group by its own id, a thread by its anchor
  // — the same keys a task's own Comments card watches.
  const watch = useMemo<Watch | undefined>(() => {
    if (!chat || chat === "missing") return undefined;
    if (chat.kind === "task" && chat.task) return { kind: "task", id: chat.task.id };
    if (chat.kind === "project" && chat.project_id)
      return { kind: "project", id: chat.project_id };
    return { kind: "chat", id: chat.id };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, chatId, taskId]);

  useRealtime(
    useCallback(
      (event) => {
        if (event.type !== "message" || event.conversation_id !== chatId) return;
        void loadNewest();
        // A rename, somebody joining or leaving: the header is the chat's own
        // fetch. Cheap, and simpler than telling those events apart.
        void loadChat();
      },
      [chatId, loadNewest, loadChat],
    ),
    watch,
  );

  /** The three-step handshake, as the task's comments do it — ticket, bytes
   *  straight to storage, confirm. */
  const upload = async (file: Blob, name: string, type: string) => {
    setUploading({ name, pct: 0 });
    try {
      const ticket = await api<Ticket>(`${base}/attachments`, {
        method: "POST",
        body: JSON.stringify({ filename: name, content_type: type }),
      });
      await putToStorage(ticket.upload_url, file, ticket.content_type, (pct) =>
        setUploading({ name, pct }),
      );
      const ready = await api<ChatAttachment>(
        `/organisations/${orgId}/attachments/${ticket.attachment.id}/confirm`,
        { method: "POST", body: "{}" },
      );
      setStaged((current) => [...current, ready]);
      return ready;
    } catch (err) {
      toast.add({ title: `Couldn't attach ${name}`, description: errorDetail(err, String(err)) });
      return null;
    } finally {
      setUploading(null);
    }
  };

  const uploadAll = async (files: File[]) => {
    for (const file of files) await upload(file, file.name, file.type);
  };

  const post = async (body: string, attachmentIds: string[]) => {
    const sent = await api<ChatMessage>(`${base}/messages`, {
      method: "POST",
      body: JSON.stringify({
        body,
        attachment_ids: attachmentIds,
        ...(replyTo ? { reply_to_id: replyTo.id } : {}),
      }),
    });
    // Your own message is in the thread now, not on the next refetch.
    scrollIntent.current = { kind: "bottom" };
    setMessages((current) => merge(current ?? [], [sent]));
    setReplyTo(null);
    onChanged();
  };

  const sendVoiceNote = async (blob: Blob, contentType: string, seconds: number) => {
    const extension = contentType.includes("mp4") ? "m4a" : "webm";
    const ready = await upload(blob, `voice-note-${Math.round(seconds)}s.${extension}`, contentType);
    if (!ready) return;
    try {
      // No caption: a message may be only files, and the player says what it is.
      await post("", [ready.id]);
      setStaged((current) => current.filter((a) => a.id !== ready.id));
    } catch {
      toast.add({ title: "Couldn't send that voice note" });
    }
  };

  /** `typed` is the box's own value at the moment Enter went down. Reading
   *  `draft` there instead can see the render *before* the last keystroke
   *  landed, and a fast typist's message silently doesn't send. */
  const send = async (typed?: string) => {
    // Files with no words are a message too — the server allows an empty
    // body exactly when there's something to attach.
    const body = (typed ?? draft).trim();
    if ((!body && staged.length === 0) || sending) return;
    setSending(true);
    try {
      await post(body, staged.map((a) => a.id));
      setDraft("");
      setStaged([]);
    } catch (err) {
      toast.add({ title: "Couldn't send that", description: errorDetail(err) });
    } finally {
      setSending(false);
    }
  };

  const { dragging, dropProps } = useFileDrop(
    (files) => void uploadAll(files),
    !canPost || !!uploading,
  );

  const setState = async (state: { pinned?: boolean; muted?: boolean; archived?: boolean }) => {
    try {
      setChat(await api<ChatOut>(`${base}/state`, { method: "PUT", body: JSON.stringify(state) }));
      onChanged();
    } catch (err) {
      toast.add({ title: "Couldn't change that", description: errorDetail(err) });
    }
  };

  const rename = async () => {
    if (!renaming?.trim()) return;
    try {
      setChat(
        await api<ChatOut>(base, { method: "PATCH", body: JSON.stringify({ title: renaming }) }),
      );
      setRenaming(null);
      onChanged();
    } catch (err) {
      toast.add({ title: "Couldn't rename it", description: errorDetail(err) });
    }
  };

  const addMembers = async () => {
    if (!adding?.length) return;
    try {
      setChat(
        await api<ChatOut>(`${base}/members`, {
          method: "POST",
          body: JSON.stringify({ user_ids: adding }),
        }),
      );
      setAdding(null);
      onChanged();
    } catch (err) {
      toast.add({ title: "Couldn't add them", description: errorDetail(err) });
    }
  };

  const leave = async () => {
    if (!me) return;
    try {
      await api(`${base}/members/${me}`, { method: "DELETE" });
      setLeaving(false);
      onChanged();
      navigate(`/orgs/${orgId}/chats`);
    } catch (err) {
      toast.add({ title: "Couldn't leave", description: errorDetail(err) });
    }
  };

  const jumpTo = (id: string) => {
    const el = scroller.current?.querySelector(`[data-message="${id}"]`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("ring-2", "ring-primary");
    setTimeout(() => el.classList.remove("ring-2", "ring-primary"), 1200);
  };

  if (chat === "missing") {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="text-sm text-muted-foreground">
          This chat doesn't exist, or you're not in it.
        </p>
        <Button variant="outline" size="sm" onClick={onBack}>
          Back to chats
        </Button>
      </div>
    );
  }

  const other =
    chat && chat.kind === "direct" ? chat.members.find((m) => m.id !== me) : undefined;
  const otherSeen = other ? (presence.get(other.id) ?? other) : undefined;
  const showAuthors = chat?.kind !== "direct";

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {/* Header */}
      <div className="flex h-14 shrink-0 items-center gap-2 border-b px-3">
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          aria-label="Back to chats"
          onClick={onBack}
        >
          <ArrowLeftIcon />
        </Button>
        {chat === null ? (
          <Spinner />
        ) : (
          <>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h2 className="truncate text-sm font-semibold">{chat.title}</h2>
                {chat.muted && (
                  <BellOffIcon
                    className="size-3.5 shrink-0 text-muted-foreground"
                    aria-label="Muted"
                  />
                )}
              </div>
              <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                {chat.kind === "task" && chat.task && (
                  <>
                    <StatusBadge status={chat.task.status} className="h-5" />
                    <PriorityGlyph priority={chat.task.priority} />
                    {chat.task.closed && <span>closed</span>}
                  </>
                )}
                {chat.kind === "project" && <span>Project comments</span>}
                {chat.kind === "group" && (
                  <span>
                    {chat.members.length} member{chat.members.length === 1 ? "" : "s"}
                    {", "}
                    {chat.members.filter((m) => (presence.get(m.id) ?? m).online).length} online
                  </span>
                )}
                {chat.kind === "direct" &&
                  (other ? (
                    <span className={cn(otherSeen?.online && "text-primary")}>
                      {seenLine(otherSeen)}
                    </span>
                  ) : (
                    <span>Notes to yourself</span>
                  ))}
              </div>
            </div>
            {chat.kind === "task" && chat.task && (
              <Button
                variant="outline"
                size="sm"
                aria-label="Open task"
                render={<Link to={`/orgs/${orgId}/tasks/${chat.task.id}`} />}
                nativeButton={false}
              >
                <ExternalLinkIcon />
                <span className="hidden sm:inline">Open task</span>
              </Button>
            )}
            {chat.kind === "project" && chat.project_id && (
              <Button
                variant="outline"
                size="sm"
                aria-label="Open project"
                render={<Link to={`/orgs/${orgId}/projects/${chat.project_id}`} />}
                nativeButton={false}
              >
                <FolderKanbanIcon />
                <span className="hidden sm:inline">Open project</span>
              </Button>
            )}
            {chat.kind === "direct" && other && (
              <Button
                variant="ghost"
                size="sm"
                render={<Link to={`/orgs/${orgId}/people/${other.id}`} />}
                nativeButton={false}
              >
                Profile
              </Button>
            )}
            <DropdownMenu>
              <DropdownMenuTrigger
                render={<Button variant="ghost" size="icon" aria-label="Chat options" />}
              >
                <MoreVerticalIcon />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-52">
                <DropdownMenuGroup>
                  <DropdownMenuItem onClick={() => void setState({ pinned: !chat.pinned })}>
                    {chat.pinned ? <PinOffIcon /> : <PinIcon />}
                    {chat.pinned ? "Unpin" : "Pin to top"}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => void setState({ muted: !chat.muted })}>
                    {chat.muted ? <BellIcon /> : <BellOffIcon />}
                    {chat.muted ? "Unmute" : "Mute"}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => void setState({ archived: !chat.archived })}>
                    {chat.archived ? <ArchiveRestoreIcon /> : <ArchiveIcon />}
                    {chat.archived ? "Unarchive" : "Archive"}
                  </DropdownMenuItem>
                </DropdownMenuGroup>
                {chat.kind === "group" && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuGroup>
                      <DropdownMenuItem onClick={() => setRenaming(chat.title)}>
                        <PencilIcon />
                        Rename
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => setAdding([])}>
                        <UserPlusIcon />
                        Add people
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => setLeaving(true)}>
                        <LogOutIcon />
                        Leave group
                      </DropdownMenuItem>
                    </DropdownMenuGroup>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        )}
      </div>

      {/* Messages */}
      <div
        ref={scroller}
        className="min-h-0 flex-1 overflow-y-auto px-3 py-4 md:px-6"
        onScroll={(e) => {
          if (e.currentTarget.scrollTop < 200) void loadOlder();
        }}
      >
        {messages === null ? (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        ) : messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-muted-foreground">
            {chat?.kind === "direct" && !other ? (
              <>
                <BookmarkIcon className="size-6" />
                Saved messages: anything you send here is only for you.
              </>
            ) : chat?.kind === "group" ? (
              <>
                <UsersIcon className="size-6" />
                Nothing said yet. Say hello.
              </>
            ) : (
              "No messages yet."
            )}
          </div>
        ) : (
          <ol className="mx-auto flex max-w-3xl flex-col gap-0.5">
            {hasMore && (
              <li className="flex justify-center py-2">
                {loadingOlder ? (
                  <Spinner />
                ) : (
                  <Button variant="ghost" size="sm" onClick={() => void loadOlder()}>
                    Load older messages
                  </Button>
                )}
              </li>
            )}
            {messages.map((m, i) => {
              const prev = messages[i - 1];
              const newDay =
                !prev || new Date(prev.created_at).toDateString() !== new Date(m.created_at).toDateString();
              const continues =
                !!prev &&
                !newDay &&
                prev.author?.id === m.author?.id &&
                new Date(m.created_at).getTime() - new Date(prev.created_at).getTime() < GROUP_MS;
              return (
                <Fragment key={m.id}>
                  {newDay && (
                    <li className="sticky top-0 z-[1] flex justify-center py-2">
                      <span className="rounded-full border bg-background/90 px-2.5 py-0.5 text-xs text-muted-foreground backdrop-blur">
                        {dayLabel(m.created_at)}
                      </span>
                    </li>
                  )}
                  <Bubble
                    orgId={orgId}
                    message={m}
                    continues={continues}
                    showAuthor={showAuthors && !m.mine && !continues}
                    mentionable={mentionable}
                    canReply={canPost}
                    onReply={() => {
                      setReplyTo(m);
                      composer.current?.querySelector("textarea")?.focus();
                    }}
                    onJump={jumpTo}
                    onChanged={(updated) =>
                      setMessages((current) => merge(current ?? [], [updated]))
                    }
                  />
                </Fragment>
              );
            })}
          </ol>
        )}
      </div>

      {/* Composer */}
      {canPost && (
        <div
          role="group"
          aria-label="Message composer"
          className={cn(
            "relative shrink-0 space-y-2 border-t px-3 py-2 md:px-6",
            dragging && "ring-2 ring-primary ring-inset",
          )}
          {...dropProps}
        >
          {dragging && (
            <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-background/80">
              <span className="flex items-center gap-2 text-sm font-medium">
                <PaperclipIcon className="size-4" />
                Drop to attach
              </span>
            </div>
          )}
          <div className="mx-auto max-w-3xl space-y-2">
            {replyTo && (
              <div className="flex items-center gap-2 rounded-md border-l-2 border-primary bg-muted/40 py-1 pr-1 pl-2 text-xs">
                <ReplyIcon className="size-3.5 shrink-0 text-primary" />
                <span className="min-w-0 flex-1 truncate">
                  <span className="font-medium">{personName(replyTo.author)}</span>{" "}
                  <span className="text-muted-foreground">{replyTo.body || "File"}</span>
                </span>
                <button
                  type="button"
                  aria-label="Cancel reply"
                  className="rounded-sm p-0.5 hover:bg-muted"
                  onClick={() => setReplyTo(null)}
                >
                  <XIcon className="size-3.5" />
                </button>
              </div>
            )}
            {staged.length > 0 && (
              <ul className="flex flex-wrap gap-2">
                {staged.map((file) => (
                  <li
                    key={file.id}
                    className="flex items-center gap-1.5 rounded-md border bg-muted/40 py-1 pr-1 pl-2 text-xs"
                  >
                    <PaperclipIcon className="size-3 shrink-0" />
                    <span className="max-w-40 truncate">{file.filename}</span>
                    <span className="font-mono text-muted-foreground">
                      {formatBytes(file.size_bytes)}
                    </span>
                    <button
                      type="button"
                      aria-label={`Remove ${file.filename}`}
                      className="rounded-sm p-0.5 hover:bg-muted"
                      onClick={() =>
                        setStaged((current) => current.filter((f) => f.id !== file.id))
                      }
                    >
                      <XIcon className="size-3" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {uploading && (
              <div className="space-y-1">
                <p className="truncate text-xs text-muted-foreground">
                  Uploading {uploading.name}…
                </p>
                <div className="h-1 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary transition-[width]"
                    style={{ width: `${Math.round(uploading.pct * 100)}%` }}
                  />
                </div>
              </div>
            )}
            <div className="flex items-end gap-1">
              <input
                ref={filePicker}
                type="file"
                className="hidden"
                multiple
                aria-label="File to upload"
                onChange={(e) => {
                  const files = Array.from(e.target.files ?? []);
                  e.target.value = "";
                  if (files.length) void uploadAll(files);
                }}
              />
              <Button
                size="icon"
                variant="ghost"
                aria-label="Attach a file"
                disabled={!!uploading}
                onClick={() => filePicker.current?.click()}
              >
                <PaperclipIcon />
              </Button>
              <div ref={composer} className="min-w-0 flex-1">
                <MentionTextarea
                  rows={1}
                  people={mentionable}
                  value={draft}
                  aria-label="Write a message"
                  placeholder="Message…"
                  className="max-h-48 min-h-9 resize-none"
                  onValueChange={setDraft}
                  onKeyDown={(e) => {
                    // Enter sends, Shift+Enter breaks the line — what every
                    // messenger does, and what the task's comments already do.
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void send(e.currentTarget.value);
                    }
                    if (e.key === "Escape" && replyTo) setReplyTo(null);
                  }}
                />
              </div>
              {canRecord() && !draft.trim() && staged.length === 0 ? (
                <VoiceNoteRecorder onRecorded={sendVoiceNote} disabled={!!uploading} />
              ) : (
                <Button
                  size="icon"
                  aria-label="Send"
                  disabled={sending || (!draft.trim() && staged.length === 0)}
                  onClick={() => void send()}
                >
                  <SendIcon />
                </Button>
              )}
            </div>
          </div>
        </div>
      )}

      <Dialog open={renaming !== null} onOpenChange={(open) => !open && setRenaming(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename group</DialogTitle>
          </DialogHeader>
          <Input
            value={renaming ?? ""}
            aria-label="Group name"
            maxLength={120}
            onChange={(e) => setRenaming(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void rename()}
          />
          <DialogFooter>
            <Button disabled={!renaming?.trim()} onClick={rename}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={adding !== null} onOpenChange={(open) => !open && setAdding(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add people</DialogTitle>
            <DialogDescription>
              They'll see everything already said in the group.
            </DialogDescription>
          </DialogHeader>
          <PeoplePicker
            people={people}
            selected={adding ?? []}
            onChange={setAdding}
            exclude={chat?.members.map((m) => m.id) ?? []}
          />
          <DialogFooter>
            <Button disabled={!adding?.length} onClick={addMembers}>
              Add {adding?.length ? adding.length : ""}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={leaving} onOpenChange={setLeaving}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Leave {chat?.title}?</DialogTitle>
            <DialogDescription>
              Your messages stay in the group. You'll need someone to add you back to see it
              again.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="destructive" onClick={leave}>
              Leave
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Bubble({
  orgId,
  message,
  continues,
  showAuthor,
  mentionable,
  canReply,
  onReply,
  onJump,
  onChanged,
}: {
  orgId: string;
  message: ChatMessage;
  /** Same person, moments after their last message: tighter, no name. */
  continues: boolean;
  showAuthor: boolean;
  mentionable: MentionPerson[];
  canReply: boolean;
  onReply: () => void;
  onJump: (id: string) => void;
  onChanged: (updated: ChatMessage) => void;
}) {
  const toast = useToastManager();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(message.body);
  const [viewing, setViewing] = useState<ChatAttachment | null>(null);

  const save = async () => {
    try {
      onChanged(
        await api<ChatMessage>(`/organisations/${orgId}/comments/${message.id}`, {
          method: "PATCH",
          body: JSON.stringify({ body: value }),
        }),
      );
      setEditing(false);
    } catch (err) {
      toast.add({ title: "Couldn't save that", description: errorDetail(err) });
    }
  };

  const remove = async () => {
    try {
      onChanged(
        await api<ChatMessage>(`/organisations/${orgId}/comments/${message.id}`, {
          method: "DELETE",
        }),
      );
    } catch (err) {
      toast.add({ title: "Couldn't delete that", description: errorDetail(err) });
    }
  };

  return (
    <li
      data-message={message.id}
      className={cn(
        "group flex rounded-lg transition-shadow",
        message.mine ? "justify-end" : "justify-start",
        !continues && "mt-2",
      )}
    >
      <div
        className={cn(
          "flex max-w-[85%] items-end gap-1 md:max-w-[70%]",
          message.mine && "flex-row-reverse",
        )}
      >
        <div
          className={cn(
            "min-w-0 rounded-2xl px-3 py-1.5 text-sm",
            message.mine ? "bg-primary text-primary-foreground" : "bg-muted",
            message.deleted && "bg-transparent italic text-muted-foreground ring-1 ring-border",
          )}
        >
          {showAuthor && !message.deleted && (
            <div className="mb-0.5 flex items-center gap-1.5 text-xs font-semibold">
              {personName(message.author)}
              {message.via && (
                <Badge variant="outline" className="h-4 px-1 text-[10px] font-normal">
                  via {message.via}
                </Badge>
              )}
            </div>
          )}
          {message.deleted ? (
            <span>Message deleted</span>
          ) : (
            <>
              {message.reply_to && (
                <button
                  type="button"
                  onClick={() => onJump(message.reply_to!.id)}
                  className={cn(
                    "mb-1 block w-full rounded-md border-l-2 px-2 py-0.5 text-left text-xs",
                    message.mine
                      ? "border-primary-foreground/60 bg-primary-foreground/10"
                      : "border-primary bg-background/60",
                  )}
                >
                  <span className="block font-medium">{personName(message.reply_to.author)}</span>
                  <span className="line-clamp-2 opacity-80">
                    {message.reply_to.deleted ? "Message deleted" : message.reply_to.body || "File"}
                  </span>
                </button>
              )}
              {editing ? (
                <div className="space-y-2 py-1">
                  <MentionTextarea
                    rows={2}
                    people={mentionable}
                    value={value}
                    aria-label="Edit message"
                    className="bg-background text-foreground"
                    onValueChange={setValue}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void save();
                      }
                      if (e.key === "Escape") setEditing(false);
                    }}
                  />
                  <div className="flex gap-2">
                    <Button size="sm" variant="secondary" aria-label="Save message" onClick={save}>
                      Save
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                message.body && (
                  <p className="break-words whitespace-pre-wrap">
                    <MentionedText body={message.body} people={mentionable} />
                  </p>
                )
              )}
              {message.attachments.length > 0 && (
                <ul className="mt-1 flex flex-wrap gap-2">
                  {message.attachments.map((file) => (
                    <li key={file.id}>
                      {isAudio(file.content_type) ? (
                        <VoiceNotePlayer url={file.url} filename={file.filename} />
                      ) : isImage(file.content_type) ? (
                        <button
                          type="button"
                          aria-label={`Open ${file.filename}`}
                          className="block overflow-hidden rounded-lg"
                          onClick={() => setViewing(file)}
                        >
                          <img
                            src={file.thumbnail_url ?? file.url}
                            alt={file.filename}
                            className="max-h-60 max-w-full object-cover"
                          />
                        </button>
                      ) : (
                        <a
                          href={file.url}
                          target="_blank"
                          rel="noreferrer"
                          className="flex items-center gap-2 rounded-lg border bg-background/60 px-2.5 py-2 text-xs text-foreground"
                        >
                          <FileIcon className="size-4 shrink-0 text-muted-foreground" />
                          <span className="max-w-48 truncate">{file.filename}</span>
                          <span className="font-mono text-muted-foreground">
                            {formatBytes(file.size_bytes)}
                          </span>
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          <div
            className={cn(
              "mt-0.5 text-right font-mono text-[10px]",
              message.mine && !message.deleted
                ? "text-primary-foreground/70"
                : "text-muted-foreground",
            )}
            title={new Date(message.created_at).toLocaleString()}
          >
            {message.edited_at && !message.deleted && "edited · "}
            {clock(message.created_at)}
          </div>
        </div>
        {!message.deleted && !editing && (
          // Hover actions, beside the bubble rather than over it, so they never
          // cover the words you're about to reply to. Always shown on touch,
          // where there is no hover.
          <div className="flex shrink-0 gap-0.5 opacity-100 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:focus-within:opacity-100">
            {canReply && (
              <Button size="icon-sm" variant="ghost" aria-label="Reply" onClick={onReply}>
                <ReplyIcon />
              </Button>
            )}
            {message.mine && (
              <>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="Edit message"
                  onClick={() => {
                    setValue(message.body);
                    setEditing(true);
                  }}
                >
                  <PencilIcon />
                </Button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="Delete message"
                  onClick={remove}
                >
                  <Trash2Icon />
                </Button>
              </>
            )}
          </div>
        )}
      </div>
      {viewing && (
        <Lightbox
          src={viewing.thumbnail_url ?? viewing.url}
          downloadUrl={viewing.url}
          alt={viewing.filename}
          onClose={() => setViewing(null)}
        />
      )}
    </li>
  );
}
