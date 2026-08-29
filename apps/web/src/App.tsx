import { useCallback, useEffect, useState } from "react";
import { Link, Outlet, useLocation, useMatch, useNavigate } from "react-router-dom";
import { signOut } from "supertokens-auth-react/recipe/session";

import { BellIcon, PlusIcon } from "lucide-react";

import { api } from "@/api";
import { AppSidebar } from "@/components/app-sidebar";
import { NewTaskDialog } from "@/components/new-task-dialog";
import { TimerBar } from "@/components/timer-bar";
import {
  SearchPalette,
  SearchTrigger,
  useSearchHotkey,
} from "@/components/search-palette";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { Spinner } from "@/components/ui/spinner";
import { Toaster, useToastManager } from "@/components/ui/toast";
import { AUTH_BASE_PATH } from "@/config";
import { lastOrg, rememberOrg } from "@/lib/current-org";
import type { Organisation, PendingInvite, Timer } from "@/lib/types";

/** How often the unread badge refreshes.
 *
 *  Polling, not a websocket: it's a counter. A second realtime channel just to
 *  keep a number current isn't worth the reconnect handling, and a minute is
 *  well inside the time it takes anyone to notice. The upgrade path is there
 *  if it ever feels slow. */
const UNREAD_POLL_MS = 60_000;

/** How often the header re-checks whether a timer is running.
 *
 *  Slow on purpose: the displayed clock ticks locally from `started_at`, so
 *  this poll only has to catch a timer started or stopped in *another tab*.
 *  Polling per second to render a predictable number would be a request per
 *  second per open tab. */
const TIMER_POLL_MS = 30_000;

export type Me = {
  id: string;
  user_id: string;
  email: string | null;
  display_name: string | null;
  /** IANA. Sent up automatically on first sight so reminders know whose day
   *  is meant — nobody has to find a setting for it to work. */
  timezone: string | null;
  /** A line you set about what you're on with, shown to colleagues. Not an
   *  organisation announcement — that has an author and an audience. */
  status_message: string | null;
  /** Opt-out, default on — see `models/user.py`'s own comment for why. */
  daily_summary_enabled: boolean;
};

/**
 * What every screen inside the shell can reach.
 *
 * `reload` exists because almost every action on a screen changes something
 * the *rail* shows — accepting an invitation adds an organisation, leaving one
 * removes it. Passing a refresh down beats each screen keeping its own copy of
 * the list and letting it drift.
 */
export type Shell = {
  me: Me | null;
  organisations: Organisation[];
  invites: PendingInvite[];
  currentOrg: Organisation | null;
  unread: number;
  remindersDue: number;
  /** The running timer, wherever it is — there is one per person. */
  timer: Timer;
  refreshTimer: () => Promise<void>;
  reload: () => Promise<void>;
  /** Nudge the badge after doing something that clears notifications, rather
   *  than waiting out the poll interval. */
  refreshUnread: () => Promise<void>;
  openCreateOrg: () => void;
};

type Gate = "loading" | "ok" | "error";

export default function App() {
  return (
    <Toaster>
      <Shell />
    </Toaster>
  );
}

/**
 * Tell the server which timezone this browser is in, if it doesn't match.
 *
 * Reminders are **dates**, so "the day before" is meaningless without knowing
 * whose day is meant. Detected rather than asked: a setting nobody finds is a
 * setting that stays wrong, and the browser already knows the answer.
 *
 * Fire-and-forget — it must never delay or fail the request the whole shell
 * blocks on. A failure just means the next sign-in tries again.
 */
async function syncTimezone(me: Me) {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (!tz || tz === me.timezone) return;
    await api("/me", { method: "PATCH", body: JSON.stringify({ timezone: tz }) });
  } catch {
    // Not worth a toast. Reminders fall back to UTC.
  }
}

function Shell() {
  const [me, setMe] = useState<Me | null>(null);
  const [organisations, setOrganisations] = useState<Organisation[]>([]);
  const [invites, setInvites] = useState<PendingInvite[]>([]);
  const [unread, setUnread] = useState(0);
  // Reminders that have come due. Cross-organisation, like the inbox — a
  // reminder you set last week must not be invisible because you're looking
  // at a different organisation today.
  const [remindersDue, setRemindersDue] = useState(0);
  const [timer, setTimer] = useState<Timer>({ entry: null, organisation_id: null });
  const [gate, setGate] = useState<Gate>("loading");
  const [creating, setCreating] = useState(false);
  const [searching, setSearching] = useState(false);
  const [creatingTask, setCreatingTask] = useState(false);

  const navigate = useNavigate();
  const { pathname } = useLocation();
  // The URL is the source of truth for which organisation is current. Reading
  // it here rather than holding it in state means Back, a bookmark and a
  // pasted link all behave the same.
  // Both called unconditionally — `a ?? b` would skip the second hook on the
  // renders where the first matches, and React counts hooks by position.
  const nested = useMatch("/orgs/:orgId/*");
  const exact = useMatch("/orgs/:orgId");
  const orgId = (nested ?? exact)?.params.orgId ?? null;
  const currentOrg = organisations.find((o) => o.id === orgId) ?? null;
  // **What the rail navigates, which is not the same as what the URL names.**
  // The organisations list, your notifications, your reminders and your
  // account all sit outside any organisation — but you are still *working in*
  // one, and losing the whole section the moment you glance at a list is how
  // you end up with no way back except clicking through it again. The
  // switcher already claims an organisation on those screens; this is what
  // makes the nav underneath agree with it.
  const railOrg =
    currentOrg ?? organisations.find((o) => o.id === lastOrg()) ?? organisations[0] ?? null;

  const reload = useCallback(async () => {
    // `/me` is in here too: the account screen changes the display name and
    // the status line, and both are rendered by the shell. Without it the
    // rail keeps showing the old one until a full reload.
    const [orgs, pending, who] = await Promise.all([
      api<Organisation[]>("/organisations"),
      api<PendingInvite[]>("/me/invites"),
      api<Me>("/me"),
    ]);
    setOrganisations(orgs);
    setInvites(pending);
    setMe(who);
  }, []);

  useEffect(() => {
    // `GET /me` is the request that creates the local user row and binds any
    // invitation waiting on this address, so it has to land before anything
    // else asks about organisations.
    api<Me>("/me")
      .then(async (data) => {
        setMe(data);
        void syncTimezone(data);
        await reload();
        setGate("ok");
      })
      .catch(() => setGate("error"));
  }, [reload]);

  const refreshUnread = useCallback(async () => {
    try {
      // Both counters on one tick. A second interval for a second number is
      // a second thing to get out of step.
      const [inbox, reminders] = await Promise.all([
        api<{ unread: number }>("/notifications/unread-count"),
        api<{ count: number }>("/reminders/due-count"),
      ]);
      setUnread(inbox.unread);
      setRemindersDue(reminders.count);
    } catch {
      // A failed poll must never break the shell. The next tick tries again.
    }
  }, []);

  useEffect(() => {
    if (gate !== "ok") return;
    void refreshUnread();
    const id = setInterval(refreshUnread, UNREAD_POLL_MS);
    return () => clearInterval(id);
  }, [gate, refreshUnread]);

  const refreshTimer = useCallback(async () => {
    try {
      setTimer(await api<Timer>("/me/timer"));
    } catch {
      // Same as the badge: a failed poll must never break the shell.
    }
  }, []);

  useEffect(() => {
    if (gate !== "ok") return;
    void refreshTimer();
    const id = setInterval(refreshTimer, TIMER_POLL_MS);
    return () => clearInterval(id);
  }, [gate, refreshTimer]);

  // Coming back to a screen is the other moment the count is likely stale.
  useEffect(() => {
    if (gate === "ok") void refreshUnread();
  }, [gate, pathname, refreshUnread]);

  useEffect(() => {
    if (orgId) rememberOrg(orgId);
  }, [orgId]);

  // Bound globally, but search is organisation-scoped — pressing it outside
  // one would have nothing to search.
  const openSearch = useCallback(() => {
    if (railOrg) setSearching(true);
  }, [railOrg]);
  useSearchHotkey(openSearch);

  const signOutTo = () => signOut().then(() => (window.location.href = AUTH_BASE_PATH));

  if (gate === "loading") {
    return (
      <div className="flex min-h-svh items-center justify-center bg-background">
        <Spinner />
        <span className="sr-only">Loading</span>
      </div>
    );
  }

  if (gate === "error") {
    return (
      <div className="flex min-h-svh flex-col items-center justify-center gap-4 bg-background p-6 text-center">
        <div className="space-y-1">
          <h1 className="text-lg font-semibold">Couldn&rsquo;t load your account</h1>
          <p className="max-w-sm text-sm text-muted-foreground">
            We couldn&rsquo;t reach the server to check who you are. Try again in a moment.
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => window.location.reload()}>Try again</Button>
          <Button variant="ghost" onClick={signOutTo}>
            Log out
          </Button>
        </div>
      </div>
    );
  }

  const shell: Shell = {
    me,
    organisations,
    invites,
    currentOrg,
    unread,
    remindersDue,
    timer,
    refreshTimer,
    reload,
    refreshUnread,
    openCreateOrg: () => setCreating(true),
  };

  return (
    <SidebarProvider>
      <AppSidebar
        me={me}
        organisations={organisations}
        currentOrg={railOrg}
        inviteCount={invites.length}
        unread={unread}
        remindersDue={remindersDue}
        onCreateOrg={() => setCreating(true)}
        onSignOut={signOutTo}
      />
      <SidebarInset>
        {/* Deliberately thin. Each screen renders its own breadcrumb and
            title, because only the screen knows where in the hierarchy it is. */}
        <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-3 border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/75">
          <SidebarTrigger />
          <Separator orientation="vertical" className="h-5" />
          <span className="truncate text-sm font-semibold">
            {currentOrg?.name ?? "Your organisations"}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <TimerBar timer={timer} onChanged={refreshTimer} />
            {/* Next to search, deliberately: the same "reachable from any
                screen without leaving it" reasoning applies to starting a
                task as to finding one. `railOrg` (not the URL's org) is what
                search already follows for the same reason — the nav claims
                an organisation even on pages that aren't inside one.
                Suppressed on the Tasks screen itself, which already has this
                exact button in its own page actions — two of them on one
                screen would be redundant, not extra convenient. */}
            {railOrg && pathname !== `/orgs/${railOrg.id}/tasks` && (
              <Button variant="outline" size="sm" onClick={() => setCreatingTask(true)}>
                <PlusIcon />
                <span className="hidden md:inline">New task</span>
              </Button>
            )}
            {railOrg && <SearchTrigger onClick={openSearch} />}
          </div>
          <Link
            to="/notifications"
            aria-label={unread ? `Notifications (${unread} unread)` : "Notifications"}
            className="relative flex size-9 items-center justify-center rounded-md hover:bg-accent"
          >
            <BellIcon className="size-4" />
            {unread > 0 && (
              <span className="absolute top-1.5 right-1.5 size-2 rounded-full bg-primary" />
            )}
          </Link>
        </header>

        <main className="flex flex-1 flex-col gap-6 p-4 md:p-6">
          <Outlet context={shell} />
        </main>
      </SidebarInset>

      {railOrg && (
        <SearchPalette
          orgId={railOrg.id}
          open={searching}
          onOpenChange={setSearching}
        />
      )}

      {railOrg && (
        // No `onCreated` — a screen showing tasks (the board, a list) already
        // refetches on the realtime `task` event this create publishes, the
        // identical path a second tab or a colleague's own change takes. A
        // second, bespoke refresh wired through the shell would just be a
        // slower duplicate of that.
        <NewTaskDialog open={creatingTask} onOpenChange={setCreatingTask} orgId={railOrg.id} />
      )}

      <CreateOrgDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={async (org) => {
          await reload();
          navigate(`/orgs/${org.id}`);
        }}
      />
    </SidebarProvider>
  );
}

function CreateOrgDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (org: Organisation) => void | Promise<void>;
}) {
  const toast = useToastManager();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      const org = await api<Organisation>("/organisations", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      setName("");
      onOpenChange(false);
      await onCreated(org);
      toast.add({ title: "Organisation created", description: `You own ${org.name}.` });
    } catch {
      toast.add({ title: "Couldn't create that", description: "Try again in a moment." });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New organisation</DialogTitle>
          <DialogDescription>
            You&rsquo;ll be its owner. Everything else — teams, projects, tasks — lives inside
            one of these.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="org-name">Name</Label>
          <Input
            id="org-name"
            autoFocus
            value={name}
            placeholder="Acme"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
        </div>
        <DialogFooter>
          <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
          <Button onClick={submit} disabled={busy || !name.trim()}>
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
