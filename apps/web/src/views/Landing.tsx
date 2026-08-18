/**
 * The front door, for people who aren't signed in.
 *
 * Everything else in this product is behind a session, so this is the only
 * screen a stranger can reach. Deliberately just a headline and the two ways
 * in — no feature list, no pitch. Someone who found a to-do app already knows
 * what a to-do app is, and a page trying to sell them on this one before
 * they've even signed up is exactly the kind of thing the tagline is joking
 * about.
 *
 * Two rules it follows:
 *
 * 1. **No colours of its own.** It reaches for the same tokens as the app, so
 *    it follows a theme change and dark mode without anyone remembering it
 *    exists — the same reasoning as `lib/auth-theme.ts`. Status owns the only
 *    red and the only amber; a marketing page inventing a third accent is how
 *    that stops being true.
 * 2. **It is not the app.** No rail, no shell, no `/me` — nothing here fetches
 *    anything, so it renders instantly and works with the API down.
 */

import { Link } from "react-router-dom";
import { AnchorIcon, ArrowRightIcon, MoonIcon, SunIcon } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { BRAND } from "@/lib/brand";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const SIGN_IN = "/auth";
// SuperTokens' pre-built page reads `show` from the query string, so the
// account CTA lands on the sign-up tab rather than on sign-in with a small
// link somebody has to find.
const SIGN_UP = "/auth?show=signup";

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
  return (
    <section className="relative z-10 py-20 text-center">
      <h1 className="mx-auto max-w-2xl text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
        {BRAND.tagline}
      </h1>

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

export function Footer() {
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
