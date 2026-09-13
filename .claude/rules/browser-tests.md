---
paths:
  - "e2e/**"
---

# Writing Playwright tests here

## Writing browser tests here

Writing browser tests here, three things bite every time:

- **`getByLabel` matches on substring**, so "Invitation link" also matches a
  "Copy invitation link" button. Prefer `getByRole("textbox", { name })`.
- **Scope to the dialog.** A modal's "Role" or "Project" select collides with
  the ones on the page behind it.
- **The copy uses typographic apostrophes** (`&rsquo;`). An ASCII `'` in an
  assertion never matches; match around it.
- **One file now appears twice on a task** — in the Files panel and in the
  comment it was posted to. Both cards are named regions, so scope with
  `getByRole("region", { name: "Files" | "Comments" })` rather than reaching
  for `.first()`, which picks whichever happens to be earlier in the DOM.
- **`getByRole("dialog")` also matches every toast on screen.** Base UI's
  toast is `role="dialog" aria-modal="false"`, so an assertion scoped to
  "the dialog" starts failing on strict mode the moment a test asserts a
  toast and then opens a popup — which is the ordinary shape of "save,
  then check the result". Scope with
  `page.locator('[data-slot="dialog-content"]')` when a toast could still
  be alive. Cost real time on the Versions dialog, where it looked like
  the dialog hadn't opened.
- **A test organisation named after the feature will collide with the
  feature's own controls.** An org called `Versions 1788…` gave the
  organisation switcher the accessible name "Versions 1788…", so
  `getByRole("button", { name: "Versions" })` opened the org menu instead
  of the dialog, and the failure screenshot showed a wide-open switcher
  with no explanation. Name test orgs after nothing in particular, and use
  `{ exact: true }` on button names that are also common words.
- **A toast title and a history line often say the same thing.** "Moved" is
  both a toast and part of "… moved it to another project". Use
  `getByRole("heading", { name, exact: true })` for the toast.
- **A label can contain another label.** `getByRole`'s name matching is
  case-insensitive *substring* by default, so "Move X" also matches
  "**Re**move X" — which is why the bookmarks list's delete button says
  "Delete X". Check a new `aria-label` against the others on the same row
  before adding it, or reach for `{ exact: true }`.
- **`PriorityGlyph` is labelled "Priority: Normal"**, which a substring match
  on "Priority" also hits. `{ exact: true }` on the control's name.
- **`CardTitle` renders a `div`, not a heading.** `getByRole("heading")` finds
  toast titles (real `h2`s) and nothing else; use `getByText` for card titles.
- **Wait for the effect, not the click.** Navigating straight after an action
  can outrun its POST — the next screen then shows the old data and the failure
  looks like a logic bug. Assert on the thing the action produced first.

```bash
# after a model change
docker compose exec api uv run alembic revision --autogenerate -m "what changed"
```

Migrations are authored in dev and committed; production applies whatever is in
the repo, via the one-shot `migrate` service. A self-hoster is never asked to
run alembic.
