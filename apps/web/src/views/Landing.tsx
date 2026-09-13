/**
 * The front door, for people who aren't signed in.
 *
 * Everything else in this product is behind a session, so this is the only
 * screen a stranger can reach. Deliberately just a headline and the two ways
 * in — no feature list, no pitch. Most installations of this are somebody's
 * own server with a handful of colleagues on it, and a marketing page in
 * front of people who were sent a link is selling them something they have
 * already been given.
 *
 * Two rules it follows:
 *
 * 1. **No colours of its own.** It reaches for the same tokens as the app, so
 *    it follows a theme change and dark mode without anyone remembering it
 *    exists — the same reasoning as `lib/auth-theme.ts`. Status owns the only
 *    red and the only amber; a marketing page inventing a third accent is how
 *    that stops being true.
 * 2. **It is not the app.** No rail, no shell, no `/me`. It makes exactly one
 *    request — `GET /api/public/settings`, unauthenticated, for the two
 *    things the operator of this installation gets to decide: what the
 *    heading says, and whether a stranger may create an account. That
 *    request failing is a state this page renders correctly (an open
 *    installation with the product's own name), so it still works with the
 *    API down.
 *
 * **Why those two are fetched rather than built in.** This product is
 * self-hosted first, and a heading compiled into the bundle is a heading
 * every installation is stuck with — `BRAND.tagline` used to be exactly
 * that. Nor can it be an environment variable: `config.ts` explains why the
 * bundle carries no build-time configuration at all (one built image has to
 * run on any domain), and closing registration during a spam wave is not a
 * thing to need a rebuild for. So it is a row, `instance_settings`, written
 * from the panel or from `scripts/instance.sh`.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AnchorIcon, ArrowRightIcon, MoonIcon, SunIcon } from "lucide-react";

import { api } from "@/api";
import { buttonVariants } from "@/components/ui/button";
import { BRAND } from "@/lib/brand";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const SIGN_IN = "/auth";
// SuperTokens' pre-built page reads `show` from the query string, so the
// account CTA lands on the sign-up tab rather than on sign-in with a small
// link somebody has to find.
const SIGN_UP = "/auth?show=signup";

/** What the operator of this installation decided about its front door. */
type PublicSettings = { landing_headline: string | null; signups_enabled: boolean };

/**
 * What an installation looks like until somebody changes it — and what this
 * page falls back to when the request fails.
 *
 * Falling back to *open* is deliberate. The server is the gate
 * (`security/authn.py`), so the worst a wrong guess here costs is a button
 * that leads to a refusal which says exactly why; guessing *closed* would
 * tell every visitor an installation was invitation-only because one fetch
 * timed out, which is a far more convincing lie.
 */
const OPEN: PublicSettings = { landing_headline: null, signups_enabled: true };

/**
 * One request per page load, shared.
 *
 * `Header`, `Hero` and `Footer` all need the answer and are three separate
 * components — two of them also render around SuperTokens' own auth screens,
 * where there is no `Landing` above them to pass a prop down from. A promise
 * cached at module scope is what makes that one request instead of three,
 * and it is never invalidated because the only thing that changes it is an
 * operator editing the panel, in another tab, in another session.
 */
let pending: Promise<PublicSettings> | null = null;

function loadPublicSettings(): Promise<PublicSettings> {
  pending ??= api<PublicSettings>("/public/settings").catch(() => OPEN);
  return pending;
}

/**
 * `null` while it is still in flight, which is not the same as "open".
 *
 * Every caller below hides the Create account control until this resolves
 * rather than showing it and taking it away: a button that appears and then
 * vanishes reads as a glitch, and on an invitation-only installation it is
 * also a button that would have gone somewhere it isn't allowed.
 */
function usePublicSettings(): PublicSettings | null {
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  useEffect(() => {
    let alive = true;
    void loadPublicSettings().then((value) => {
      if (alive) setSettings(value);
    });
    return () => {
      alive = false;
    };
  }, []);
  return settings;
}

export default function Landing() {
  return (
    <div className="relative flex min-h-dvh flex-col overflow-x-hidden bg-background text-foreground">
      <Backdrop />
      <Header />

      <main className="relative mx-auto flex w-full max-w-5xl flex-1 items-center justify-center px-6">
        <Hero />
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

export function Header() {
  const { theme, toggle } = useTheme();
  const settings = usePublicSettings();

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
        {settings?.signups_enabled && (
          <Link to={SIGN_UP} className={cn(buttonVariants(), "h-8 px-3")}>
            Create account
          </Link>
        )}
      </div>
    </header>
  );
}

export function Wordmark() {
  return (
    <Link to="/" className="flex items-center gap-2.5">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
        <AnchorIcon className="size-4" />
      </span>
      <span className="text-sm font-semibold tracking-tight">{BRAND.name}</span>
    </Link>
  );
}

function Hero() {
  const settings = usePublicSettings();
  // An empty headline is stored as NULL rather than "" precisely so this
  // falls back rather than rendering a page with no heading — see
  // `models/instance_settings.py`. `||` not `??` so a stray empty string
  // from anywhere behaves the same way.
  const headline = settings?.landing_headline || BRAND.name;

  return (
    <section className="relative z-10 py-20 text-center">
      <h1 className="mx-auto max-w-2xl text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
        {headline}
      </h1>

      <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
        {settings?.signups_enabled && (
          <Link to={SIGN_UP} className={cn(buttonVariants(), "h-10 gap-2 px-5 text-sm")}>
            Create an account
            <ArrowRightIcon className="size-4" />
          </Link>
        )}
        <Link
          to={SIGN_IN}
          className={cn(buttonVariants({ variant: "outline" }), "h-10 px-5 text-sm")}
        >
          Sign in
        </Link>
      </div>

      {settings !== null && !settings.signups_enabled && (
        // Only once the answer is actually known — rendered while loading it
        // would tell an open installation's visitors the opposite of the
        // truth for as long as the request takes.
        <p className="mx-auto mt-6 max-w-md text-sm text-muted-foreground text-balance">
          This installation is invitation only. Ask an administrator to invite you — opening
          the link they send is how you get an account.
        </p>
      )}
    </section>
  );
}

export function Footer() {
  const settings = usePublicSettings();

  return (
    <footer className="relative z-10 border-t border-border">
      <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center gap-x-6 gap-y-3 px-6 py-8 text-sm text-muted-foreground">
        <Wordmark />
        <div className="flex-1" />
        <Link to={SIGN_IN} className="hover:text-foreground">
          Sign in
        </Link>
        {settings?.signups_enabled && (
          <Link to={SIGN_UP} className="hover:text-foreground">
            Create account
          </Link>
        )}
      </div>
    </footer>
  );
}
