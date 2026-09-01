import {
  BellIcon,
  CalendarDaysIcon,
  CalendarIcon,
  CircleDotIcon,
  ClockIcon,
  CommandIcon,
  CompassIcon,
  FolderKanbanIcon,
  KeyRoundIcon,
  NotebookIcon,
  PackageIcon,
  SearchIcon,
  SendIcon,
  ServerCogIcon,
  ShieldCheckIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router-dom";

import { PageHeader } from "@/components/page-header";
import { BRAND } from "@/lib/brand";

type Section = { id: string; title: string; icon: LucideIcon };

// The same icon the rail uses for the equivalent nav item, where there is
// one — a section about Tasks carries the identical glyph the Tasks link
// in the sidebar does, so the two visibly correspond.
const SECTIONS: Section[] = [
  { id: "overview", title: "Overview", icon: CompassIcon },
  { id: "organisations", title: "Organisations & people", icon: UsersIcon },
  { id: "projects", title: "Projects & sharing", icon: FolderKanbanIcon },
  { id: "tasks", title: "Tasks", icon: CircleDotIcon },
  { id: "search", title: "Search", icon: SearchIcon },
  { id: "time", title: "Time tracking", icon: ClockIcon },
  { id: "planner", title: "Planner", icon: CalendarDaysIcon },
  { id: "calendar", title: "Calendar & reminders", icon: CalendarIcon },
  { id: "notepad", title: "Notepad", icon: NotebookIcon },
  { id: "notifications", title: "Notifications", icon: BellIcon },
  { id: "telegram", title: "Telegram", icon: SendIcon },
  { id: "security", title: "Two-factor authentication", icon: ShieldCheckIcon },
  { id: "export", title: "Taking your data out", icon: PackageIcon },
  { id: "api", title: "Your own assistant, and the API", icon: KeyRoundIcon },
  { id: "shortcuts", title: "Keyboard shortcuts", icon: CommandIcon },
  { id: "admin", title: "Running this installation", icon: ServerCogIcon },
];

const ICON_FOR: Record<string, LucideIcon> = Object.fromEntries(
  SECTIONS.map((s) => [s.id, s.icon]),
);

/**
 * The user manual. Not a marketing page — Landing.tsx already covers "what
 * is this" for someone who hasn't signed up. This is for someone who has,
 * and wants to know what's possible without hunting for it screen by
 * screen. Reachable from the bottom of the rail, deliberately unobtrusive:
 * it sits beside the theme toggle and Log out, not in the main navigation
 * a first-time visitor's eye lands on.
 */
export default function Help() {
  return (
    <>
      <PageHeader
        crumbs={[{ label: "Help" }]}
        title="Help"
        description={`What ${BRAND.name} does, and how to get at it.`}
      />

      <div className="grid gap-8 lg:grid-cols-[14rem_1fr]">
        <nav className="hidden lg:block">
          <ul className="sticky top-4 space-y-1 text-sm">
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className="block rounded-md px-2 py-1 text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                >
                  {s.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="max-w-3xl space-y-10 text-sm leading-relaxed">
          <Section id="overview" title="Overview">
            <p>
              {BRAND.name} is organisations, projects and tasks — or just tasks with no
              project, for the kind of thing that doesn&rsquo;t belong to one. Everything is
              private until someone shares it: a new organisation, project or task starts
              visible only to whoever created it.
            </p>
            <p>
              Switch organisations from the icon at the top of the rail. Most of the rail
              changes with it — Tasks, Projects, Planner and the rest all belong to whichever
              organisation is current. Your inbox, reminders and account settings don&rsquo;t;
              they sit below a divider because they follow you, not the organisation.
            </p>
          </Section>

          <Section id="organisations" title="Organisations & people">
            <p>
              Create one from the switcher. You own it, and can invite people from{" "}
              <strong>People</strong> in the rail — by email, if the installation sends mail,
              or with a copyable link that works either way. The link is the one that always
              works: paste it into any chat and whoever opens it joins by clicking, no email
              required.
            </p>
            <p>
              Three roles: <strong>member</strong> sees only what&rsquo;s shared with them,{" "}
              <strong>admin</strong> can see and administer everything in the organisation, and{" "}
              <strong>owner</strong> can additionally rename or delete it and hand out the
              owner role itself. An admin is the escape hatch when something needs sorting out
              — a project whose only member left, say.
            </p>
            <p>
              The organisation&rsquo;s dashboard leads with two things worth knowing about:{" "}
              <strong>announcements</strong> (posted by an admin, everyone sees them) and{" "}
              <strong>out of office</strong> (set your own from Account, and it shows on
              everyone&rsquo;s dashboard a fortnight ahead — the point is a colleague checks
              before asking you for something).
            </p>
          </Section>

          <Section id="projects" title="Projects & sharing">
            <p>
              A project is private to whoever creates it, full stop — not even an
              organisation admin can see it until it&rsquo;s shared, or until they need the
              admin escape hatch above. Share it with a specific person or a whole team, at{" "}
              <strong>Read</strong> or <strong>Write</strong>, from the project&rsquo;s own
              page. A single task can also be shared on its own, without sharing the whole
              project it&rsquo;s filed in — do that from the task screen&rsquo;s own sharing
              card.
            </p>
            <p>
              <strong>Project groups</strong> are labels for tidiness, nothing more — filing a
              project in one doesn&rsquo;t grant anybody access to it. Archive a project you&rsquo;re
              done with rather than deleting it if you might want the history later; both,
              along with handing over ownership, live on the project&rsquo;s own page.
            </p>
          </Section>

          <Section id="tasks" title="Tasks">
            <p>
              Every task has a <strong>status</strong> (To do, In progress, Review, On hold,
              Blocker) and, separately, whether it&rsquo;s <strong>closed</strong> — a task can
              close from any status, because closing and finishing aren&rsquo;t always the
              same thing. <strong>Priority</strong> is a separate six-level scale shown as a
              small chevron, Normal by default.
            </p>
            <p>
              View the list as a <strong>board</strong> (grouped by status or priority) or a{" "}
              <strong>list</strong> (sortable, filterable, one row per task) — toggle in the
              top right of Tasks. A view you&rsquo;ve filtered or sorted lives in the address
              bar, so you can send the exact link to a colleague.
            </p>
            <p>
              The <strong>owner</strong> is the only person who can close a task (an
              organisation admin can too). <strong>Action required</strong> is different: at
              most one person, who gets a nudge the moment you set it, and the owner hears
              back the moment they clear it. Due date, and separately an estimated start date
              and estimated hours, are there for planning and don&rsquo;t drive anything else
              automatically.
            </p>
            <p>
              <strong>Depends on</strong> links one task to another it&rsquo;s waiting on — purely
              informational, so closing a task with an open dependency still works; it&rsquo;s
              there so you can see at a glance what&rsquo;s actually blocking you.{" "}
              <strong>Tags</strong> are shared vocabulary across the organisation, and one
              particular tag property — taking a task <em>off the board</em> — is how you keep
              a reference item (a runbook, a checklist that isn&rsquo;t really "to do") out of
              the way without deleting it; it stays fully searchable.
            </p>
            <p>
              A task also carries <strong>checklists</strong> (more than one, if you like),{" "}
              <strong>sheets</strong> (a grid — rows and columns you name yourself, a checkbox
              at each intersection, for "run the same three checks across twenty servers"),{" "}
              <strong>files</strong> (drag and drop, or paste a screenshot straight into the
              description) and a <strong>comment thread</strong> with realtime updates and
              voice notes. A <strong>private note</strong> on a task is yours alone — nobody
              else, including an admin, can ever read it. <strong>Pin</strong> a task to have
              it follow you to your dashboard.
            </p>
            <p>
              <strong>Hiding</strong> a task is the one place access gets taken away rather
              than given: only the actual owner can do it, and while hidden, nobody else can
              see it — not even an organisation admin. Un-hiding restores exactly who could
              see it before.
            </p>
          </Section>

          <Section id="search" title="Search">
            <p>
              Press <kbd className="rounded border px-1 font-mono text-xs">⌘K</kbd> (or{" "}
              <kbd className="rounded border px-1 font-mono text-xs">Ctrl K</kbd>) from
              anywhere to search tasks, projects and your own notes across the current
              organisation. It&rsquo;s typo-tolerant, and it only ever shows you things you
              could already open — search doesn&rsquo;t leak what sharing already hides.
            </p>
          </Section>

          <Section id="time" title="Time tracking">
            <p>
              One running timer at a time, across every organisation — starting a new one
              stops whatever was already running, and the header shows a live clock wherever
              you are. Prefer to log after the fact? Type it the way you&rsquo;d say it out
              loud — "1h30", "45", "1.5h" all work. Rollups by person, project or task are on
              the Time screen.
            </p>
          </Section>

          <Section id="planner" title="Planner">
            <p>
              Your own board over the tasks you can see: a pool of unplanned work on one side,
              and five buckets — Today, Tomorrow, This week, Next week, Someday — on the
              other. Drag a task into a bucket, or do it by keyboard. It&rsquo;s personal:
              putting a task in your Today doesn&rsquo;t move it for anyone else.
            </p>
          </Section>

          <Section id="calendar" title="Calendar & reminders">
            <p>
              The <strong>calendar</strong> shows every visible task&rsquo;s due date (shared,
              like the task list itself), your own reminders (private), and everyone&rsquo;s
              out-of-office, on one month grid. A <strong>reminder</strong> can hang off a
              task or stand alone, and warns you once the day before and once on the day —
              moving it clears both warnings, so it doesn&rsquo;t go quiet forever after a
              snooze.
            </p>
          </Section>

          <Section id="notepad" title="Notepad">
            <p>
              Free-form personal notes, scoped to an organisation and autosaved as you type —
              for the kind of thing that isn&rsquo;t about any one task. Only you ever see
              your own notes here.
            </p>
          </Section>

          <Section id="notifications" title="Notifications">
            <p>
              One inbox, in the rail, across every organisation you&rsquo;re in. Open a
              notification to jump to what changed and mark it read at once, or use the
              per-row buttons to mark read or delete without leaving the list — "Mark all
              read" clears everything in one go.
            </p>
            <p>
              Where a nudge <em>also</em> reaches you is configured from{" "}
              <Link to="/account" className="underline underline-offset-2">
                Account → Notification channels
              </Link>
              : email always exists, and you can add Telegram or a generic webhook, then
              choose which kinds of notification go to which channel in the table underneath.
            </p>
          </Section>

          <Section id="telegram" title="Telegram">
            <p>
              Link a chat from Account → Notification channels — it opens a deep link, tap
              Start in Telegram and you&rsquo;re linked. Once linked, the bot understands:
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li>
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                  /task &lt;title&gt;
                </code>{" "}
                — create a task. A second line onward becomes its description.
              </li>
              <li>
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                  /org &lt;name&gt;
                </code>{" "}
                — if you&rsquo;re in more than one organisation, choose which one{" "}
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">/task</code>{" "}
                files into. Belong to exactly one? It&rsquo;s picked automatically.
              </li>
              <li>
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">/help</code> —
                a reminder of all of this, from inside the chat itself.
              </li>
            </ul>
            <p>
              A plain message, with no command, creates nothing — it has to be an explicit{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">/task</code>, on
              purpose, so a stray reply in the chat never accidentally becomes a task.
            </p>
          </Section>

          <Section id="security" title="Two-factor authentication">
            <p>
              Turn it on yourself from Account, any time — scan the QR code with an
              authenticator app and keep the ten backup codes it gives you somewhere safe. An
              organisation can also require it for everyone; if you haven&rsquo;t already set
              it up when that happens, you&rsquo;re asked to at your next sign-in, not mid-session.
              Lost your device? An organisation admin can reset your two-factor setup from the
              People roster.
            </p>
          </Section>

          <Section id="export" title="Taking your data out">
            <p>
              Build a ZIP of everything you can see — one folder per task, its files inside —
              from an organisation&rsquo;s own <strong>Settings</strong> screen (in the rail,
              near the bottom) for everything, or from a single project&rsquo;s own page to
              scope it to just that project. It builds in the background; come back and
              download it once it says Ready. Nobody else, not even an admin, can see or
              download <em>your</em> export — it only ever reflects your own access.
            </p>
          </Section>

          <Section id="api" title="Your own assistant, and the API">
            <p>
              Connect an AI assistant (Claude Code, or anything else that speaks MCP) to your
              own account from{" "}
              <Link to="/account" className="underline underline-offset-2">
                Account → Access tokens
              </Link>
              . Make a token — read-only to start, or read/write if you want it to create
              tasks and comment as you — and copy the command shown right after, which
              connects it in one step. A token only ever reaches what <em>you</em> can reach.
            </p>
            <p>
              Prefer to script against the REST API directly? It&rsquo;s fully documented,
              with a try-it-yourself explorer, at{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">/api/docs</code>{" "}
              on this same address — no separate host or port to find.
            </p>
          </Section>

          <Section id="shortcuts" title="Keyboard shortcuts">
            <ul className="list-disc space-y-1 pl-5">
              <li>
                <kbd className="rounded border px-1 font-mono text-xs">⌘K</kbd> /{" "}
                <kbd className="rounded border px-1 font-mono text-xs">Ctrl K</kbd> — search,
                from anywhere
              </li>
              <li>
                <kbd className="rounded border px-1 font-mono text-xs">Esc</kbd> — close
                whatever&rsquo;s open on top: a dialog, a picker, search itself
              </li>
              <li>Arrow keys move through a picker&rsquo;s or search&rsquo;s results; Enter chooses one</li>
            </ul>
          </Section>

          <Section id="admin" title="Running this installation">
            <p className="text-muted-foreground">
              Only relevant if you&rsquo;re the one who set this installation up — everyone
              else can skip this section.
            </p>
            <p>
              Email and Telegram are both optional infrastructure: leave them unconfigured and
              the product still works, with an honest message instead of a dead link wherever
              they&rsquo;d otherwise be used. To turn Telegram on:
            </p>
            <ol className="list-decimal space-y-2 pl-5">
              <li>
                Message{" "}
                <a
                  href="https://t.me/BotFather"
                  target="_blank"
                  rel="noreferrer"
                  className="underline underline-offset-2"
                >
                  @BotFather
                </a>{" "}
                on Telegram, <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                  /newbot
                </code>
                . It gives you a token.
              </li>
              <li>
                Set both variables in the server&rsquo;s <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">.env</code>:
                <pre className="mt-1 overflow-x-auto rounded-lg bg-muted p-3 font-mono text-xs">
{`TELEGRAM_BOT_TOKEN=<the token BotFather gave you>
TELEGRAM_BOT_USERNAME=<the bot's username, no leading @>`}
                </pre>
              </li>
              <li>
                Restart the stack so <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">api</code> and{" "}
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">worker</code> actually
                pick up the new variables — editing <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">.env</code> alone
                does nothing until they do:
                <pre className="mt-1 overflow-x-auto rounded-lg bg-muted p-3 font-mono text-xs">
                  docker compose up -d
                </pre>
              </li>
              <li>
                Register the webhook once, from anywhere that can reach the internet — this is
                what tells Telegram where to send messages. Needs a real{" "}
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">https://</code>{" "}
                site address; Telegram&rsquo;s own servers have to be able to reach it, so it
                won&rsquo;t work against <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                  http://localhost
                </code>
                :
                <pre className="mt-1 overflow-x-auto rounded-lg bg-muted p-3 font-mono text-xs">
                  {"curl \"https://api.telegram.org/bot<TOKEN>/setWebhook?url=<SITE_URL>/api/telegram/webhook\""}
                </pre>
              </li>
            </ol>
            <p>
              Still seeing "Telegram notifications aren&rsquo;t configured on this
              installation" after all four steps? The two usual culprits are a typo in the
              username (no <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">@</code>, exact case) or
              the stack not having actually restarted.
            </p>
            <p>
              Email works the same way, with <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">SMTP_HOST</code> and
              friends — see the README that came with this installation for the full list of
              settings, backups, and everything else about running it.
            </p>
          </Section>
        </div>
      </div>
    </>
  );
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  const Icon = ICON_FOR[id];
  return (
    <section id={id} className="scroll-mt-4 space-y-3">
      <h2 className="flex items-center gap-2 text-lg font-semibold">
        <Icon className="size-4 text-muted-foreground" />
        {title}
      </h2>
      {children}
    </section>
  );
}
