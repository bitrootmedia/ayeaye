---
paths:
  - "apps/api/src/app/services/attachments.py"
  - "apps/api/src/app/services/exports.py"
  - "apps/api/src/app/storage/**"
  - "apps/api/src/app/models/export.py"
  - "apps/api/src/app/tasks/thumbnails.py"
  - "apps/api/src/app/tasks/exports.py"
  - "apps/web/src/lib/audio.ts"
  - "apps/web/src/lib/storage.ts"
  - "apps/web/src/components/voice-note.tsx"
  - "apps/web/src/components/files-panel.tsx"
  - "apps/web/src/hooks/use-file-drop.ts"
  - "scripts/e2e-attachments.sh"
  - "scripts/e2e-exports.sh"
  - "e2e/tests/attachments.spec.ts"
  - "e2e/tests/voice-notes.spec.ts"
  - "e2e/tests/drag-drop.spec.ts"
---

# Attachments, voice notes, storage and data export

## Attachments

Read `services/attachments.py`. The bytes go **browser → storage directly**
and never pass through the API — a phone video must not occupy a worker for two
minutes — and that forces the three-step shape. (`app/mcp/server.py`'s
`attach_file` is the one deliberate exception, for a caller that isn't a
browser and has no route to the bucket of its own — see the MCP section.)

1. ticket (access checked, type validated, `pending` row, presigned PUT);
2. the browser PUTs to storage;
3. **confirm** — HEAD the object, enforce the size limit against the **real**
   size, flip to `ready`.

**Step 3 is the only point at which the API can inspect an upload.** A client
that declares "image/png" and uploads 60MB of something else is caught there
and nowhere else. `scripts/e2e-attachments.sh` does exactly that, through real
storage.

Things that will bite:

- **Content-Type is signed byte for byte.** The server normalises
  `audio/webm;codecs=opus` to `audio/webm`, signs *that*, and returns it for
  the client to echo. Sending the browser's own `file.type` back would fail
  with `SignatureDoesNotMatch`, which says nothing about codecs. This is the
  voice-note trap from PLAN.md §6, handled once for every file type.
- **`handle /media/*`, never `handle_path`.** The bucket is called `media` and
  addressing is path-style, so the object URL *is* `/media/<key>` and the path
  is covered by the signature. Stripping the prefix breaks every upload.
- **Two S3 endpoints.** Internal for our own calls, public for signing, because
  SigV4 covers the Host header. The public one defaults to `SITE_URL`, which is
  right whenever Caddy fronts `/media/*`.
- **A presigned URL is a bearer token until it expires.** Minted fresh at read
  time, never stored and never sent over the realtime channel.
- **`message_id` is nullable**: the attachment row exists before the comment.
  Binding is scoped to the conversation, the uploader, `message_id IS NULL` and
  `status = 'ready'` — each clause blocks a different way of borrowing someone
  else's upload.
- **The captured `XMLHttpRequest` in `lib/storage.ts`** is kept, but *not* for
  the reason the reference needed it. Single origin means uploads are
  same-origin, so the CORS-preflight failure it worked around cannot happen
  here. It stays so no interceptor mutates a signature-bound request, and for
  upload progress. It still breaks if a caller is behind `React.lazy`.

### One table, two anchors

`attachments` (renamed from `message_attachments` in `0009`) is anchored to
**a task or a conversation**, never both and never neither — a CHECK on
`num_nonnulls(task_id, conversation_id) = 1` says so, and a second CHECK stops
a `message_id` existing without a conversation.

Both live in one table because the task's Files panel shows both. A file
dropped into a reply is exactly as much "a file on this task" as one added
from the panel, and the question people ask is "where's the survey PDF", never
"was it attached or posted". `attachments_service.for_task()` is one statement
with an OR over the two anchors, so ordering stays the database's job.
Comment-sourced rows are filtered to `message_id IS NOT NULL`: something
staged and never sent is not on the task.

**Comment files can't be deleted from the panel.** The comment refers to them;
removing one from underneath would leave a message pointing at nothing. Delete
the comment instead. The UI omits the button rather than showing one that 403s.

**Both upload points take a drop** — the task's Files panel and the comment
composer, via `hooks/use-file-drop.ts`. Three things there are load-bearing:

- **`dragleave` fires when the pointer crosses onto a child**, so the hook
  counts depth (enter increments, leave decrements, zero means out). Without
  it the highlight strobes as you move across the panel.
- **`dragover` must `preventDefault()` on every event**, not just the first,
  or the browser refuses the drop and the drag just ends.
- **`main.tsx` cancels `dragover`/`drop` on the window.** Missing a drop
  target by twenty pixels is the normal case, and the browser's default for a
  dropped file is to *open* it — throwing away a half-written comment and
  everything else on the page.

Multiple files upload sequentially: there is one progress bar, and four
parallel uploads on a phone connection is four slow ones rather than one fast
one.

**Thumbnails are a worker job** (`tasks/thumbnails.py`, Pillow, 480px max
edge, EXIF transposed, alpha flattened onto white). `thumbnail_url` being
`None` is a real answer — the job may not have run yet, or it isn't an image —
and the UI falls back to the original. A worker that is down costs bandwidth,
not a broken image.

Two things that cost time here:

- **The worker needs its own S3 credentials.** They were on `api` and not on
  `worker`, so every thumbnail failed with `InvalidAccessKeyId` while the API
  looked perfectly healthy.
- **A task in `app/tasks/` that isn't imported by `app/tasks/__init__.py`
  silently doesn't exist.** The worker logs "task … is not found. Maybe you
  forgot to import it?" and nothing else happens. `tests/test_task_registry.py`
  now fails the build instead.

## Data export

Read `services/exports.py` and `models/export.py`. "Take your data" — a ZIP
per organisation or per project, one directory per task, its files inside.
Built in the worker (`tasks/exports.py`), the same reasoning `thumbnails.py`
already established: an organisation-wide export can mean hundreds of tasks
and their attachments, and building that inline would risk an HTTP timeout
and hold a request open for no reason when this container exists for
exactly this shape of work.

**Privacy: no branch that grants anybody else access, not even an admin —
the one rule that matters most here.** The zip's contents are the
*requester's own* `access.visible_tasks_stmt` result at build time, not
"everything in the organisation," so letting a different member — even an
org admin — download someone else's export would leak tasks that member
couldn't otherwise see. Every read in `services/exports.py` filters on
`requested_by_user_id == caller`, the identical absence-of-a-branch
discipline `services/notes.py` and `services/personal_notes.py` already
hold for their own private data. `scripts/e2e-exports.sh` proves this is
the one property worth testing hardest: an admin gets an empty list and a
404 on both status and download for a colleague's export.

**Autodelete after a confirmed download.** The server can't observe the
actual browser → storage transfer — that GET goes straight to S3, same as
every other download in this product (see Attachments) — so "confirmed"
means the one honest signal actually available: the person asked for the
file. `GET .../download` stamps `downloaded_at` the first time only (a
second click just re-mints the presigned URL without moving the clock, so
double-clicking Download can't postpone deletion), and a new scheduled
sweep, `sweep_expired_exports` (`:45` past the hour, next to
reminders/deadlines/the digest at `:05`/`:15`/`:25`), deletes the object and
flips `status` to `expired` once either that stamp is past a grace window
(`EXPORT_GRACE`, five minutes — long enough for a large zip on a slow
connection to finish) or, for one nobody ever downloads,
`created_at` is past a longer ceiling (`EXPORT_MAX_AGE`, seven days) — the
same "never claimed still shouldn't leak forever" reasoning applied to a
second, independent condition in the same claim. Re-requesting a download
on an `expired` row is `410 Gone`, not `404` — it existed and is gone on
purpose, a different fact from "never existed" (wrong owner) or "not ready
yet" (`409`).

**`services/exports.py::claim_expired` clears `storage_key` in a *second*,
separate statement from the one that claims the row — found writing it, not
guessed.** `RETURNING` reflects the row *after* an `UPDATE`, so a single
statement that both nulls `storage_key` and returns it hands back `NULL`
every time — exactly the key the caller needs to actually delete the S3
object. The claim itself (the part that has to be race-safe, the identical
`UPDATE … WHERE … RETURNING` shape `reminders.claim` already uses) is
entirely in the first statement; by the time the second one runs, only the
winner holds those ids, so it needs no claim of its own.

**Two new batched-by-many-task-ids functions, because this is the one
caller that would otherwise be N+1 across however many tasks are in
scope**, the same discipline every list endpoint in this codebase already
follows for a single page: `services/attachments.py::for_tasks` (mirrors
the existing `for_messages`'s batched-by-ids shape exactly) and
`services/conversations.py::for_tasks` (mirrors `list_messages`, minus the
tombstones — a removed comment already has its body cleared by `remove()`,
so there's nothing of the person's own words left to export, and it's left
out entirely rather than shown as a placeholder). `services/tags.py::for_tasks`
already existed and needed no counterpart. Checklists don't get one:
`checklists_service.for_task` stays a per-task loop in the builder, on
purpose — this is a background job with no request latency to protect, not
a live list endpoint, and the "one statement" discipline is specifically
about the requests a person is waiting on.

**The description in `task.md` is deliberately *not*
`richtext.to_plain_text()`.** That function collapses everything to one
line for a search snippet, which would turn a multi-paragraph description
into a wall of text here. `tasks/exports.py::_description_text` is a
second, small, export-only converter — block tags become line breaks, `<li>`
becomes a bullet, then the rest strips the same way — kept local to this
module specifically so the shared single-line contract other callers
(search) depend on stays untouched.

**Folder naming checks for *any* alphanumeric character before calling
`slugify`, not after.** A title of nothing but punctuation (`"!!!"`) has
nothing for `slugify` to keep, and its own fallback for that case is
`"org"` — the right word for a URL stem with no organisation name, the
wrong one for a task folder with no readable title. `_task_folder` decides
`"untitled"` itself rather than letting that fallback leak into a context
it wasn't written for. The first 8 characters of the task's own id are
appended regardless, so two tasks slugifying to the same stem still land in
different folders — and the identical short-id-prefix trick disambiguates
two attachments on the same task that happen to share a filename, which a
plain `filename` can't guarantee on its own.

**An org-wide export nests task folders one level under a project
folder** (or `no-project/` for a loose task); a project-scoped export skips
that level, since the scope is already the folder root. **A task-level
grant can reach further than its project's own** — the same gap
`effective_task_level` documents elsewhere — so the builder resolves every
project a *visible task* points at directly, not "projects this caller can
see": the task screen's own breadcrumb already established that a task's
project name is fair to show even without project-level access, and this
is the identical case.

## Voice notes

`lib/audio.ts` and `components/voice-note.tsx`. They ride the attachment
machinery — same three-step handshake, same upload function — rather than
having a path of their own.

- **`bareType()` is the trap.** `MediaRecorder` reports
  `audio/webm;codecs=opus`; the signature covers Content-Type byte for byte, so
  the parameter has to go. Both ends normalise, and a browser test asserts the
  `PUT` header has no `codecs` and that storage returned 200 — the second half
  is what actually proves the signature matched.
- **Tap to start, tap to send.** Not hold-to-record: holding is hostile on a
  trackpad and to anyone who can't sustain a press, and it makes a long note
  impossible. Cancel is its own button.
- **The send button IS the send** — a voice note uploads and posts in one
  action. A typed draft is deliberately left alone, because that's a separate
  message the person hasn't finished. There's a test for that.
- **`preferredMimeType()` asks rather than assumes.** Safari has no webm
  encoder and `new MediaRecorder(stream, {mimeType: "audio/webm"})` throws
  there outright.
- **The waveform is decoded from the real audio**, so it shows where the speech
  is. When a container can't be decoded it falls back to a plain progress bar
  rather than drawing an invented shape. Decoded on every load — storing peaks
  alongside the row is the upgrade if threads get long.
- **Always release the tracks.** Without `stream.getTracks().forEach(stop)` the
  browser's recording indicator stays on after cancelling or navigating away,
  which is both alarming and a real privacy problem.
- **Chromium reports `Infinity` for a played-back note's `duration`, and it
  rendered as the literal string "Infinity:NaN".** A MediaRecorder-produced
  webm never carries a real duration in its container header, so `<audio>`'s
  `loadedmetadata` fires with `duration === Infinity` until something forces
  a seek to the actual end of the stream. `Infinity || 0` doesn't catch it —
  `Infinity` is truthy — so it flowed straight into `clock()`, where
  `Infinity - position` is still `Infinity`, `Math.floor(Infinity / 60)` is
  `Infinity`, and `Infinity % 60` is `NaN`. Playback itself was never
  affected: `onTimeUpdate` reports real positions off the raw stream
  regardless of what `duration` says. Fixed two ways — `clock()`
  (`lib/audio.ts`) now guards `Number.isFinite()` before formatting anything,
  so no future caller can reproduce this by another path; and
  `VoiceNotePlayer`'s `onLoadedMetadata` (`components/voice-note.tsx`) runs
  the standard workaround when it sees `Infinity` — seek to a huge timestamp
  (`1e101`), which makes Chromium scan to the stream's real end and fire
  `durationchange` with the true value, then seek back to `0` before anyone
  sees the jump. `onTimeUpdate` ignores position updates while that probe is
  in flight (`probingDuration` ref), or the seek itself would flash the
  progress bar to 100% and back.

Testable because Chromium has a fake capture device:
`--use-fake-device-for-media-stream --use-fake-ui-for-media-stream`, set per
spec in `e2e/tests/voice-notes.spec.ts`.

## Traps carried forward from the reference

- **Capture `window.XMLHttpRequest` at module load, before `SuperTokens.init()`
  runs.** SuperTokens patches both `fetch` and `XMLHttpRequest` and injects
  `st-auth-mode` into requests it doesn't own. RustFS answers
  `Allow-Headers: *` alongside `Allow-Credentials: true`, which browsers refuse
  to treat as a wildcard, and RustFS has no way to configure allowed headers —
  so the fix has to be client-side. Copy `packages/ui/src/lib/storage.ts` with
  its comment intact. It breaks if a caller is ever behind `React.lazy`.
- **Voice notes must send the bare content type** (`audio/webm`, never
  `audio/webm;codecs=opus`) because the presigned signature covers Content-Type
  byte for byte. Chrome/Firefox produce webm, Safari mp4. Copy the unit test.
- **Two S3 endpoints.** `S3_ENDPOINT` is what the API calls; presigned URLs are
  signed against `S3_PUBLIC_ENDPOINT`, because SigV4 covers the Host header.
  The bucket is called `media` so the object URL is literally `/media/<key>`
  and Caddy can pass it through with **no** prefix stripping — stripping would
  invalidate every signature.
