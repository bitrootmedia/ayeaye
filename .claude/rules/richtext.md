---
paths:
  - "apps/api/src/app/services/richtext.py"
  - "apps/web/src/components/rich-text*.tsx"
  - "scripts/e2e-task-revisions.sh"
  - "e2e/tests/rich-text.spec.ts"
---

# Rich task descriptions, sanitising and mermaid

## Rich task descriptions

Read `services/richtext.py`. A description is **sanitised HTML** now, and that
one change touches three things people don't expect:

**The client is never trusted.** The editor emits tidy markup and that is
irrelevant — anyone can `PATCH` a `<script>` with curl, and the next person to
open the task runs it. Every write goes through `sanitise()` and an
**allow-list**, because a block-list is a list of the attacks somebody already
thought of. `dangerouslySetInnerHTML` in `RichText` is safe *only* because of
this; don't point it at anything that hasn't been through that function.

**Search must not match markup.** `ILIKE '%div%'` against stored HTML matches
every task in the database, and snippets would show tags instead of prose.
`tasks.description_text` is a **generated column** — Postgres strips the tags,
so it cannot drift the way a column maintained in Python would, needs no
backfill and no second write path. Search and snippets read it; nothing else
does. `regexp_replace` is immutable, which is what makes it indexable.

**An image is an attachment, not a URL.** A presigned URL expires, so storing
one would fill a description with dead images within the hour. The body holds
`data-attachment-id` and nothing else; the server mints a fresh URL per read,
batched per page. Two consequences worth having: a `src` from the client is
*dropped*, so a description can't load a tracking pixel from someone else's
server — and a pasted screenshot is a task attachment like any other, so it
turns up in the Files panel with no second mechanism.

**Markdown is a second way in, not a second storage shape.** `richtext.py`'s
`from_markdown()` converts markdown to HTML and hands it back — it does not
sanitise, because markdown is just another way to *arrive* at HTML, not a
second trust boundary; every caller still runs the result through
`sanitise()` exactly as it would for hand-typed HTML. This exists because
the browser editor was never the only writer: a curl script or an MCP client
would rather send `**bold**` than build `<strong>` tags, and before this,
that text rendered completely literally — asterisks and all — via the
plain-text fallback below. Two things about the conversion are specific to
this product's own allow-list, not markdown in general:

- **A markdown `#` is promoted to `##`, and anything past `###` folds down
  to `###`.** The editor's own toolbar only ever produces `h2`/`h3`
  (`heading: { levels: [2, 3] }`), and `sanitise()` would otherwise silently
  unwrap `h1` or `h4`–`h6` into plain text — a heading disappearing is a
  worse outcome than one clamped to the size this product actually has.
- **An image reference (`![alt](url)`) renders as nothing.** The "image is
  an attachment, not a URL" rule above doesn't bend for markdown either —
  there's no way to put a `data-attachment-id` on a markdown image, so
  `sanitise()`'s orphan-`<img>` strip removes it, same as a hand-typed
  `<img src="...">` in the HTML editor. The picture has to be attached
  separately (`attach_file`/`attach_article_file` over MCP, or the Files
  panel).

Reached via an explicit `description_format`/`body_format: "html" |
"markdown"` field on the REST write endpoints (`POST/PATCH /tasks`,
`PATCH /kb/revisions/{id}`), defaulting to `"html"` — the browser's Tiptap
editor keeps sending real HTML exactly as before, so this is zero-risk for
every existing caller including the frontend itself. MCP's `create_task`
and `edit_article` tools take the more opinionated path and treat their
`description`/`body` as markdown unconditionally, no flag to set: that's
what a language model actually writes, and a plain sentence with no markdown
syntax converts to itself wrapped in one `<p>`, never a worse outcome than
the old literal-text rendering. `fenced_code` is the one markdown extension
enabled — a triple-backtick block is how anyone writing markdown expects a
code block, and it happens to emit `class="language-python"` already, the
exact shape `_LANGUAGE_CLASS` expects, with no remapping needed the way
headings need. `tests/test_richtext.py` pins the conversion against
`sanitise()` together, because a case that looks right before sanitising
and wrong after it is the only kind of bug that actually matters here.

Things that will bite:

- **Tiptap's `Image` node silently drops unknown attributes.** `TaskImage`
  re-declares `data-attachment-id` with `parseHTML`/`renderHTML`; without it
  the id survives exactly until the first round trip and every picture goes
  blank.
- **The editor keeps the URL that `confirm` returned.** The body stores only
  the id and the server adds `src` on read — so before the first save there is
  nothing to display, and a freshly pasted screenshot rendered as its own alt
  text. An upload that worked, looking exactly like one that hadn't. The copy
  is for the current editing session only; `sanitise()` drops `src` on write,
  so nothing stale is ever stored.
- **A toolbar button must `preventDefault` on mousedown.** Otherwise clicking
  it blurs the editor, the chain's `.focus()` restores it a tick later, and
  the first character typed afterwards is swallowed — it cost the first letter
  of every emphasised word.
- **Old descriptions are plain text and stay that way.** A one-way conversion
  of everybody's data, to fix rendering, is a trade nobody asked for. `RichText`
  detects the absence of `<` and renders with `whitespace-pre-wrap`.
- **No font families and no text colours.** Colour in this product means
  status; a description that can paint itself red can imitate "blocked". Code
  blocks are the exception — there the colour carries syntax.

**Mermaid diagrams needed no backend change at all.** A fenced ` ```mermaid `
block already survives `sanitise()` untouched — `mermaid` matches
`_LANGUAGE_CLASS`'s `language-[a-z0-9+#-]{1,20}` pattern, the identical
allow-list a syntax-highlighted `language-python` block already relies on —
so a diagram written or sent via markdown (including through the
`create_task`/`edit_article` MCP tools) stores correctly today with zero
schema work. The only thing missing was rendering it, which is entirely a
`components/rich-text.tsx` concern:

- **`RichText` splits sanitised HTML on `<pre><code class="language-mermaid">`
  blocks** and swaps each one for a `MermaidDiagram` component instead of
  the usual single `dangerouslySetInnerHTML`. The common case — no diagram
  in the description — stays exactly the one-`div` shape it always was;
  splitting only happens when a mermaid block is actually present.
- **`mermaid` is dynamically imported**, never bundled into the main chunk —
  it's a few hundred KB and the overwhelming majority of descriptions never
  use it, so the common case shouldn't pay for a library it never loads.
- **`securityLevel: "strict"` is not optional.** Mermaid's own DSL supports
  `click` directives that can run arbitrary JS or navigate on click, and a
  diagram's source text is exactly as untrusted as anything else that
  arrived through `sanitise()` — "the client is never trusted" applies to
  the diagram's own syntax, not just the HTML around it.
- **A rendered diagram doesn't hear about a theme toggle on its own.**
  `useTheme` (`lib/theme.ts`) owns the toggle button's own `useState`, which
  a diagram component mounted elsewhere has no way to read — so a diagram
  rendered before a dark-mode click would otherwise freeze in whatever
  theme was current at mount, sitting as a bright box on a suddenly-dark
  page. `MermaidDiagram`'s own `useIsDarkMode` hook instead observes the
  `.dark` class mutation `useTheme` makes on `<html>` directly
  (`MutationObserver`, `attributeFilter: ["class"]`), so an open diagram
  redraws the moment the surrounding page does.
- **The editor shows raw DSL text, never a live-rendered diagram.** Tiptap's
  code block already syntax-highlights as you type via lowlight; mermaid
  isn't a highlighting language lowlight knows, so a `language-mermaid`
  block just sits in plain monospace while editing (added to `LANGUAGES`
  purely so it's selectable from the code-block dropdown, with a comment
  explaining it isn't for highlighting). This is also why editable
  descriptions — `TaskDetail.tsx`'s `Details`, `ArticleDetail.tsx`'s
  `Editor` — both grew a small **Write/Preview toggle**: the task or
  article's own owner is exactly the person who wrote the diagram, and
  without a way to see it rendered without leaving edit mode, the one
  person actually drawing a diagram would never see it themselves. Preview
  renders the current draft through the identical `RichText` the read-only
  view uses — one rendering path, not two.
