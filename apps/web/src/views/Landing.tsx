/**
 * The front door, for people who aren't signed in.
 *
 * Everything else in this product is behind a session, so this is the only
 * screen a stranger can reach — which makes it the only place that has to
 * *explain* rather than assume. It is deliberately short: someone who found a
 * self-hosted task manager already knows what a task manager is, and the two
 * questions actually worth answering are "what is different about this one"
 * and "where do I sign in".
 *
 * Three rules it follows:
 *
 * 1. **Every claim on it is true of the code.** A landing page that oversells
 *    is the first thing a new person catches you on, and the second thing they
 *    stop believing is the documentation.
 * 2. **No colours of its own.** It reaches for the same tokens as the app, so
 *    it follows a theme change and dark mode without anyone remembering it
 *    exists — the same reasoning as `lib/auth-theme.ts`. Status owns the only
 *    red and the only amber; a marketing page inventing a third accent is how
 *    that stops being true.
 * 3. **It is not the app.** No rail, no shell, no `/me` — nothing here fetches
 *    anything, so it renders instantly and works with the API down. Which is
 *    the state a self-hoster is most likely to be in when they first see it.
 */

import { Link } from "react-router-dom";
import {
  AnchorIcon,
  ArrowRightIcon,
  CheckIcon,
  ClockIcon,
  LayoutDashboardIcon,
  LockIcon,
  MessageSquareIcon,
  MoonIcon,
  SearchIcon,
  SparklesIcon,
  SunIcon,
} from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { BRAND } from "@/lib/brand";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const SIGN_IN = "/auth";
// SuperTokens' pre-built page reads `show` from the query string, so the
// account CTA lands on the sign-up tab rather than on sign-in with a small
// link somebody has to find.
const SIGN_UP = "/auth?show=signup";

const FEATURES = [
  {
    icon: LockIcon,
    title: "Private until you share it",
    body: "A project is yours the moment you make it. Access goes to a named person or a named team, at read or write — and the screen lists who has it, so nobody has to reason about inheritance.",
  },
  {
    icon: LayoutDashboardIcon,
    title: "A board and a list",
    body: "Group the board by status or by priority. Sort and filter the list by any column. Both live in the URL, so the view you are looking at is one you can send to a colleague.",
  },
  {
    icon: ClockIcon,
    title: "Time, without the timesheet",
    body: "One timer, wherever you are; starting another stops it. Type hours the way you say them — 1h30. Corrections keep a trail, so a total that changed has an explanation.",
  },
  {
    icon: MessageSquareIcon,
    title: "The conversation is on the work",
    body: "Comments, files, pasted screenshots and voice notes, all on the task itself. Every open tab updates live over a websocket, and email nudges only when something is actually waiting on you.",
  },
  {
    icon: SearchIcon,
    title: "Search that can't overshare",
    body: "Fuzzy search across tasks and projects from anywhere. Permissions are resolved in the same query as the text, so a result you cannot open is a result you never see.",
  },
  {
    icon: SparklesIcon,
    title: "Bring your own assistant",
    body: "Connect Claude, or any MCP client, with a personal token. It acts as you: what you can reach, it can reach, and not one row more.",
  },
] as const;

export default function Landing() {
  return (
    <div className="relative min-h-dvh overflow-x-hidden bg-background text-foreground">
      <Backdrop />
      <Header />

      <main className="relative mx-auto w-full max-w-5xl px-6">
        <Hero />
        <Features />
        <SelfHost />
      </main>

      <Footer />
    </div>
  );
}

/**
 * The only decoration on the page.
 *
 * A grid drawn from `--border` and a wash of `--primary`, both faded out with
 * a mask so the content sits on plain background where the text is. Inline
 * styles rather than arbitrary Tailwind values because these read as one
 * gradient each; as class strings they are unreviewable.
 */
function Backdrop() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-[38rem]">
      <div
        className="absolute inset-0 opacity-60"
        style={{
          backgroundImage:
            "linear-gradient(to right, var(--border) 1px, transparent 1px)," +
            "linear-gradient(to bottom, var(--border) 1px, transparent 1px)",
          backgroundSize: "56px 56px",
          // Fades to nothing well inside the layer's own box. A mask that is
          // still part-opaque where the element ends draws a rectangle, and a
          // hard-edged rectangle of faint grid lines reads as a rendering
          // fault rather than as texture.
          maskImage: "radial-gradient(ellipse 120% 100% at 50% 0%, #000 0%, transparent 72%)",
        }}
      />
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            "radial-gradient(ellipse 55% 45% at 50% -10%, " +
            "color-mix(in oklch, var(--primary), transparent 84%), transparent 70%)",
        }}
      />
    </div>
  );
}

function Header() {
  const { theme, toggle } = useTheme();

  return (
    <header className="relative z-10 border-b border-transparent">
      <div className="mx-auto flex h-16 w-full max-w-5xl items-center gap-3 px-6">
        <Wordmark />
        <div className="flex-1" />
        <button
          type="button"
          onClick={toggle}
          aria-label={theme === "dark" ? "Light" : "Dark"}
          className={cn(buttonVariants({ variant: "ghost", size: "icon" }))}
        >
          {theme === "dark" ? <SunIcon /> : <MoonIcon />}
        </button>
        <Link to={SIGN_IN} className={cn(buttonVariants({ variant: "ghost" }), "h-8 px-3")}>
          Sign in
        </Link>
        <Link to={SIGN_UP} className={cn(buttonVariants(), "h-8 px-3")}>
          Create account
        </Link>
      </div>
    </header>
  );
}

function Wordmark() {
  return (
    <span className="flex items-center gap-2.5">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
        <AnchorIcon className="size-4" />
      </span>
      <span className="text-sm font-semibold tracking-tight">{BRAND.name}</span>
    </span>
  );
}

function Hero() {
  return (
    <section className="relative z-10 pt-16 pb-16 text-center sm:pt-24">
      <p className="mx-auto inline-flex items-center gap-2 rounded-full border border-border bg-card/70 px-3 py-1 text-xs text-muted-foreground backdrop-blur">
        <span className="size-1.5 rounded-full bg-[var(--status-progress)]" />
        Self-hosted. One hostname, one command.
      </p>

      <h1 className="mx-auto mt-6 max-w-3xl text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
        {BRAND.tagline}
      </h1>

      <p className="mx-auto mt-5 max-w-2xl text-base leading-relaxed text-pretty text-muted-foreground sm:text-lg">
        A complete place to run work with a handful of people — projects, tasks,
        time, files and the conversation around them. It lives on a machine you
        control, and nothing on it leaves that machine.
      </p>

      <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
        <Link to={SIGN_UP} className={cn(buttonVariants(), "h-10 gap-2 px-5 text-sm")}>
          Create an account
          <ArrowRightIcon className="size-4" />
        </Link>
        <Link
          to={SIGN_IN}
          className={cn(buttonVariants({ variant: "outline" }), "h-10 px-5 text-sm")}
        >
          Sign in
        </Link>
      </div>
    </section>
  );
}

function Features() {
  return (
    <section className="relative z-10 grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-3">
      {FEATURES.map(({ icon: Icon, title, body }) => (
        <article key={title} className="bg-card p-6">
          <Icon className="size-5 text-primary" />
          <h2 className="mt-4 text-sm font-semibold tracking-tight">{title}</h2>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
        </article>
      ))}
    </section>
  );
}

/**
 * The section that is really the product decision.
 *
 * "Self-hosted" is a promise most projects make and few keep past the first
 * page of the README, so this states the actual shape of it — two commands,
 * and the thing that usually stops people (SMTP) explicitly not required.
 */
function SelfHost() {
  return (
    <section className="relative z-10 my-20 grid gap-8 rounded-xl border border-border bg-card p-8 sm:grid-cols-[1fr_auto] sm:items-center">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">Yours to run</h2>
        <p className="mt-3 max-w-md text-sm leading-relaxed text-muted-foreground">
          Two commands and a hostname. The database, the queue, object storage
          and the reverse proxy come up together, migrations apply themselves,
          and HTTPS is automatic once the hostname is a real one.
        </p>
        <ul className="mt-5 space-y-2 text-sm text-muted-foreground">
          {[
            "Works on localhost with no edits at all.",
            "Email is optional — invites still produce a link you can paste.",
            "Your data is a Postgres volume and a folder of files.",
          ].map((line) => (
            <li key={line} className="flex items-start gap-2.5">
              <CheckIcon className="mt-0.5 size-4 shrink-0 text-primary" />
              {line}
            </li>
          ))}
        </ul>
      </div>

      <pre className="overflow-x-auto rounded-lg border border-border bg-muted/50 p-4 font-mono text-xs leading-6 text-foreground">
        <code>
          <span className="text-muted-foreground">$ </span>./scripts/setup.sh{"\n"}
          <span className="text-muted-foreground">$ </span>docker compose up -d
        </code>
      </pre>
    </section>
  );
}

function Footer() {
  return (
    <footer className="relative z-10 border-t border-border">
      <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center gap-x-6 gap-y-3 px-6 py-8 text-sm text-muted-foreground">
        <Wordmark />
        <span className="hidden sm:inline">{BRAND.tagline}</span>
        <div className="flex-1" />
        <Link to={SIGN_IN} className="hover:text-foreground">
          Sign in
        </Link>
        <Link to={SIGN_UP} className="hover:text-foreground">
          Create account
        </Link>
      </div>
    </footer>
  );
}
