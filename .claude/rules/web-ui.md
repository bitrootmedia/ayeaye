---
paths:
  - "apps/web/src/**"
---

# Frontend: routing, Base UI, dialogs, pickers, the shell

## The front door

`views/Landing.tsx` is the **only screen a signed-out visitor can reach**, and
`Root` in `main.tsx` is what decides that. It sits in front of the whole app
route, so the pathname test is load-bearing: **only the bare `/` is public**.
Every deeper URL still falls through to `SessionAuth`, which is what carries
`redirectToPath` and lands somebody on the page they were actually following
after they sign in. Drop the test and every "please sign in" becomes a
marketing page with the original link thrown away.

Two things follow from it being outside the shell:

- **It fetches exactly one thing**, and it isn't `/me`: `GET
  /api/public/settings`, unauthenticated, for the two facts the operator of
  the installation owns — the heading, and whether a stranger may create an
  account. A failure falls back to *open, product's own name*, which is a
  real state rather than a placeholder, so the page still works with the API
  down. `Header`, `Hero` and `Footer` all need the answer and two of them
  also render around SuperTokens' own screens, so the promise is cached at
  module scope: one request per page load, not three.
- **It restates no colours**, same rule as the auth screens. Every value comes
  from the tokens, so it follows dark mode and a palette change on its own. A
  landing page with its own accent is a second scale, and status owns the only
  red and the only amber.

**Deliberately just a headline and the two ways in — no feature list, no
pitch, no self-hosting sales copy.** It used to be `BRAND.tagline` ("Just
another take on the to-do app."), and **there is no tagline any more**: the
heading is `instance_settings.landing_headline`, written from the Instance
panel's Front door card or from `scripts/instance.sh headline`, falling back
to `BRAND.name`. That is a product decision rather than a refactor — this is
self-hosted first, and a sentence compiled into the bundle is a sentence
every installation is stuck with. Don't put one back. Anything that wants to
be configurable here belongs in that row, not in `brand.ts` and not in a
`VITE_*` variable (`config.ts` says why the bundle carries no build-time
configuration at all).

**The Create account controls — three of them, hero, header and footer —
are hidden when `signups_enabled` is false, and hidden *until the answer
arrives* rather than shown and taken away.** A button that appears and
vanishes reads as a glitch, and on a closed installation it is also a button
that goes somewhere it isn't allowed. The invitation-only note is the
opposite case and renders only once the answer is known, since showing it
while loading would tell an open installation's visitors the reverse of the
truth. **None of it is the gate** — `security/authn.py`'s `sign_up_post`
override is, and it refuses with a sentence saying to ask for an invitation.
SuperTokens' own `/auth` page still offers its Sign Up tab, deliberately
unpatched: `SuperTokens.init` runs at module load before anything is
fetched, the identical reason `EmailVerification.init` is registered
`OPTIONAL` and gated by `App.tsx` instead.

**The favicon is `apps/web/public/favicon.svg`** — the wordmark's own tile,
the same rounded square and Lucide anchor `Wordmark` renders. It restates
`--primary` as a hex literal because a favicon is drawn outside the document
and can't read a custom property; that is the one place in this product a
token colour is written twice, and it is written out in full so a palette
change shows up as a visible mismatch rather than drifting.

**The sign-in/sign-up/reset screens carry the same header and footer.** They
are SuperTokens' own routes — `getSuperTokensRoutesForReactRouterDom` hands
back a flat list of `<Route>`s with their own absolute paths, so they can't be
nested under a layout route the way `orgs/:orgId/*` is under `Root`.
`AuthChrome` in `main.tsx` wraps the whole `<Routes>` tree instead and checks
the pathname against `AUTH_BASE_PATH`; everywhere else it's a no-op
passthrough, since the app shell already supplies its own chrome. `Header`,
`Footer` and `Wordmark` are exported from `views/Landing.tsx` for exactly this
reuse — a second copy would drift from the first the next time either
changes. `Wordmark` is a link to `/`, deliberately: without it `/auth` was a
dead end with no way back except the browser's own Back button, which doesn't
exist if it's the tab's first page.

**An unmatched URL needs a wildcard route, or the page is blank — not just
without content, `Root` itself never renders.** `<Route path="/" element={<Root />}>`
with children only matches a path its children actually cover; a URL none of
them declare doesn't match the parent either, so nothing in the tree renders
at all — no rail, no header, nothing to click, which is a worse failure than
a 404 page because there's no indication anything is even running. `views/NotFound.tsx`
is the last child under `Root`, on `path="*"`, and being the *last* child
matters no more than any other route here (React Router tries children in
order, and a wildcard placed earlier would swallow paths meant for routes
declared after it — this one just happens to be declared last because
everything above it is declared first). It renders inside the same `Root` →
`SessionAuth` → `App` chain as everything else, so signed out it asks for a
sign-in first (with `redirectToPath` carrying the bad URL, exactly like any
other deep link) and only signed in does it actually show "Nothing here" —
inside the shell, rail and header intact, because it's a 404 *inside* the
app, not instead of it.

## The in-app user manual

`views/Help.tsx`, at `/help`. Landing.tsx already answers "what is this" for
someone who hasn't signed up yet, deliberately with no feature list (see its
own section above); Help answers a different question — "what can I actually
do with this" — for someone who has, and who'd otherwise have to find each
feature by clicking around. Linked from the bottom of the rail, beside the
theme toggle and Log out rather than in the main navigation: **deliberately
unobtrusive**, the exact placement asked for, because it's a reference
screen you reach for on purpose, the identical reasoning the People roster's
own move off the dashboard already established for this codebase.

**One page, not a multi-page docs site.** Nineteen sections, a sticky anchor
table of contents down the left on `lg` and up (`<nav>` of plain `<a
href="#id">` links, no scroll-spy JS — a reader either arrives from the TOC
or scrolls, and both already work with nothing fancier than
`scroll-mt-4` on each `<section>`), content on the right. Each section's
heading carries the identical icon the rail uses for the nav item it
describes where one exists (Tasks the same glyph as the Tasks link, Time
tracking the same as Time), so the two visibly correspond — a small thing,
but it's what makes "which of these do I want" answerable at a glance
rather than by reading every heading.

**User-facing language throughout, not this file's own voice.** No
`services/access.py`, no "resolves to owner", no file paths — a reader here
is asking "how do I share a project," not "how is sharing implemented." Two
sections link to real screens (`/account`, for tokens and notification
channels) because those are personal, cross-organisation routes Help can
name directly; nothing here links to an organisation-scoped screen like
Tasks or Settings, because Help itself carries no organisation context to
build that URL from — those are described in words ("your organisation's
Settings screen, near the bottom of the rail") instead of guessed at.

**Finding this prompted a real fix, not just a new page.** Writing the
"your own assistant, and the API" section and wanting to point at
interactive API docs surfaced that they were never reachable outside
development. FastAPI's own defaults put `/docs`, `/redoc` and
`/openapi.json` at the bare root; Caddy proxies only `/api/*`, `/mcp*`,
`/health` and `/media/*`, and the API's own port is published in dev alone
(see "Running and testing" below) — so in any real self-hosted deployment,
a request to `/docs` fell through Caddy's catch-all to the SPA, which has
no route there either, and rendered "Nothing here" instead of Swagger UI.
`main.py::create_app` now passes `docs_url="/api/docs"`,
`redoc_url="/api/redoc"` and `openapi_url="/api/openapi.json"` to
`FastAPI(...)`, moving all three under the one prefix that's actually
proxied everywhere — the identical "single origin, no flag to remember"
reasoning behind decision 3 in this file's own opening section, just
reaching a corner FastAPI's own defaults hadn't.

`screenshots.spec.ts` photographs the page (`14b-help`, right after
Account) in both themes, alongside everything else it already covers.

**"Running this installation," the last section, is the one deliberate
exception to "user-facing language throughout."** It's operator content —
the exact Telegram bot setup steps (a token from @BotFather, both env vars,
restarting the stack, registering the webhook with `curl`) already in
README's own "Telegram — notifications, and creating tasks from chat — is
optional too" section — placed here too because a self-hoster hitting
"Telegram notifications aren't configured on this installation" while
signed into their own instance is faster served by a page already open
than by finding the README on disk. Explicitly labelled as skippable
("only relevant if you're the one who set this installation up") rather
than gated on a role, because Help carries no notion of "administers this
installation" at all — that's an operator role, not an organisation one,
and this codebase has no account attribute for it (see the "no policy
engine" decision at the top of this file) to gate on even if it wanted to.

## Gotchas in the frontend

- **`GET /me` is not just a fetch.** It creates the local user row on first
  sight, and from Phase 1 it binds pending invites. The shell blocks on it
  before rendering anything, or children fire requests against a user that
  doesn't exist yet.

- **`useMatch(a) ?? useMatch(b)` is a hook-order bug.** `??` short-circuits, so
  the second hook is skipped on renders where the first matches and React
  counts hooks by position. Call both, then choose. (`App.tsx` resolves the
  current organisation this way.)

- **A detail screen must be keyed to the thing it shows, or going straight
  from one to another carries the last one's state along.** Reported as
  "jump to a task from ⌘K while already on a task and the title stays from
  the previous one" — and it was exactly that: both tasks match
  `orgs/:orgId/tasks/:taskId`, so React Router keeps the same component
  instance, and `Details`' `useState(task.title)` only ever runs on mount.
  Everything fed straight from props (the heading, the pickers, the
  breadcrumb) updated around it, which is what made it look like only
  *some* fields were stale — the title and the description were the two
  held in local state. The same `useState(x.name)` shape sat unnoticed in
  `ProjectDetail` and `BookDetail`; the task screen also carried its
  collapsed-panel state, a half-typed delete confirmation and a
  half-written comment across. `Keyed` in `main.tsx` wraps all four detail
  routes and keys them on their id param, so a different thing is a
  different screen. **Fix the class, not the field:** syncing each field
  with an effect works until the next field is added, and the remount
  costs nothing here — everything on these screens already refetches on
  the id, and `use-realtime`'s 250ms linger exists precisely so
  subscription churn drops nothing. Pinned by "the editable fields belong
  to the task you arrived at" in `task-ux.spec.ts`, which fails on the
  title without the key.

- **`noUnusedLocals` is on**, and shadcn sometimes generates an unused `React`
  import. One-line fix when it happens; worth keeping the check.
- **The whole app is inside an `ErrorBoundary`, and it earned its place.** A
  render error unmounts the *entire* React tree — not the component, not the
  screen — leaving a white page with no rail and nothing to click. That is
  what "the site goes to localhost and shows nothing" means when somebody
  reports it. `/__crash` is a dev-only route that throws so the boundary can
  be tested rather than assumed; `import.meta.env.DEV` is a compile-time
  constant, so it and its component vanish from a production build.
- **Base UI's `DropdownMenuLabel` must be inside a `DropdownMenuGroup`.** It
  reads a context only `Menu.Group` provides and *throws* on open otherwise.
  The organisation switcher had it as a sibling, so the first click anybody
  ever gave it blanked the product — through a hundred green browser tests,
  none of which had opened a menu.
- **The breadcrumb separator is a sibling of the item, not a child.** Both
  render `<li>`, and nesting them is invalid HTML that React logs on every
  screen with a breadcrumb.
- **`EntityPicker`'s list is a `Popover.Portal`, not a plain `absolute` div —
  and that isn't a style choice, it's the fix for a real bug.** The original
  hand-rolled version positioned its list `absolute` inside the field's own
  wrapper, which every `Card` clips: `Card`'s base classes carry
  `overflow-hidden` unconditionally (for rounding cover images to its
  corners), so any picker whose list would extend past its card's own bottom
  edge — Priority and Project on the task screen, reliably, because they
  aren't the first field in their card — had that list silently cut off.
  Status and Owner, the first field in each of their cards, mostly didn't,
  which is exactly the kind of intermittent, position-dependent symptom that
  reads as "sometimes" until someone maps it to card position. Portaling to
  `document.body` escapes that ancestor chain entirely, and
  `Popover.Positioner` is what supplies `--anchor-width` / `--available-height`
  (the same primitives `DropdownMenuContent` already uses) — for free, that
  also fixes the picker running off the bottom of the viewport on a short
  screen, which the old version never handled either.
- **Base UI's own dismissal replaced two hand-rolled `document` listeners,
  and correctly, not just more concisely.** The picker used to bind its own
  `mousedown` (click-away) and capture-phase `keydown` (Escape, stopped
  before it could also close an enclosing dialog) listeners directly on
  `document`. Once the list is portaled, that click-away check breaks in a
  new way: a click *inside* the now-elsewhere-in-the-DOM list reads as
  "outside" the field's own wrapper and would close the picker before the
  click's own handler ever registered the choice. `Popover`'s built-in
  dismissal (`useDismiss`, floating-ui's nested-floating-tree logic) already
  solves both — outside-click detection that correctly excludes its own
  portaled content, and Escape that closes only the innermost floating
  layer — which is the same "innermost thing closes first" behavior the
  hand-rolled capture-phase trick existed to fabricate. Confirmed, not
  assumed: `e2e/tests/task-ux.spec.ts`'s "Escape closes the list, not the
  dialog behind it" still passes unchanged.
- **A native `<input type="date">`'s calendar glyph is browser-drawn and
  ignores every design token.** It doesn't take `color`, doesn't take
  `fill`, and is always near-black — invisible against a dark input, on
  every `type="date"` field in the product (task due date, estimate start,
  reminders, out-of-office). `filter: invert(1)` on
  `::-webkit-calendar-picker-indicator`, scoped to `.dark`, is the only
  lever Chromium/Safari expose for it — one rule in `index.css`'s base
  layer fixes every instance at once rather than each screen needing its
  own patch. Firefox draws this control differently and isn't a target
  here; the product's own e2e suite runs Chromium.
- **A dialog taller than the viewport used to grow off the top *and* the
  bottom of it at once, with nothing anywhere allowed to scroll.**
  `DialogContent` is `fixed top-1/2 left-1/2 -translate-y-1/2` — centred,
  so overflow is symmetrical — and it carried no `max-height` and no
  `overflow`. Reported against the new-task dialog, where `Textarea`'s
  default `field-sizing-content` (the same auto-growing behaviour the
  notepad's own editor documents) means the description field grows with
  every line typed until the Title field is above the screen and Create is
  below it, both unreachable, no scrollbar in sight. Latent in *every*
  dialog, not that one. Fixed in two places, deliberately:
  `DialogContent`'s base classes gained `max-h-[calc(100dvh-2rem)]
  overflow-y-auto` as a **safety net** — `dvh` so a phone's collapsing
  browser chrome can't hide the footer — so the worst any dialog can now
  do is scroll as a whole. That is a hand edit inside
  `components/ui/`, which is generated: re-adding `dialog` to update it
  drops the fix silently, and every dialog in the product goes back to
  being able to grow off-screen. And a dialog that would rather pin its header
  and footer says so itself with `flex flex-col` plus a `min-h-0 flex-1
  overflow-y-auto` body, which `NewTaskDialog` now does and the notepad's
  editor already did (`cn`'s tailwind-merge lets that `flex` replace the
  base `grid`). Two things about the fix are load-bearing: **`min-h-0` on
  the scrolling body** — a flex child's default `min-height: auto` floors
  it at its content's height, so `flex-1` alone lets it push the footer
  out of the dialog instead of scrolling, the exact vertical twin of the
  `min-w-0` trap the duplicate-title box on the same dialog already
  documents — and **`overflow-hidden` on any popup that scrolls
  internally**, or the base `overflow-y-auto` leaves it a second scroll
  container nested around the first. Nothing floating was clipped by the
  new overflow because `EntityPicker` and every menu already portal to
  `document.body`; the search palette was already `overflow-hidden` for
  its own results list. Pinned by `e2e/tests/task-ux.spec.ts`'s "a long
  description leaves the title and Create reachable", which asserts on
  **geometry, not `toBeVisible`** — every control stayed rendered and
  "visible" all along, which is exactly why nothing caught this earlier;
  the test reads the popup's own bounding box (it sat at `y = -501.5`
  before the fix) and calls `scrollIntoViewIfNeeded`, which has nothing to
  scroll on a `fixed` popup with no scroll container inside it.

## Base UI, not Radix

- **Base UI, not Radix.** Triggers take `render={<Button />}`, not `asChild`;
  `Select` needs an `items` prop. `Button render={<a/>} nativeButton={false}`
  puts `role="button"` on the anchor, so a test's `getByRole("link")` won't
  find it.
