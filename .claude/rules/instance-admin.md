---
paths:
  - "apps/api/src/app/services/instance.py"
  - "apps/api/src/app/api/routers/instance.py"
  - "apps/api/src/app/models/instance_admin.py"
  - "apps/api/src/app/models/instance_settings.py"
  - "apps/api/src/app/api/routers/public.py"
  - "apps/web/src/views/Landing.tsx"
  - "apps/api/src/app/cli/**"
  - "apps/web/src/views/Instance*.tsx"
  - "scripts/instance.sh"
  - "scripts/e2e-instance.sh"
  - "e2e/tests/instance.spec.ts"
---

# Instance administration

## Instance administration

Read `services/instance.py`. Who is on this installation, and stopping
abuse — reached two ways now: `scripts/instance.sh`, and the web panel at
`/instance` for anybody holding an `instance_admins` row.

**It shipped as a shell tool alone, and this file argued for that at
length.** The argument was that a web backoffice becomes the single
highest-value account on an instance — phishable and brute-forceable in a way
an SSH key is not — guarding data that organisation admins deliberately
cannot reach. That argument still holds, and it is the reason for every
restriction below. What changed is a product decision: an operator should be
able to do this from the app. So the mitigations are what survived, and they
are load-bearing rather than decorative.

**1. The panel cannot appoint its own successors.** `instance_admins` rows
are granted and revoked from the shell only (`grant-admin`/`revoke-admin`).
There is no route that hands one out, and `scripts/e2e-instance.sh` asserts
that by walking the OpenAPI document rather than trusting the code to stay
that way. One stolen session cannot become a permanent foothold, and cannot
widen past itself.

**2. An instance admin gets no extra power inside any organisation.**
`services/access.py` never learns the table exists — a hidden task stays
hidden from them, a private note stays private, an export stays the
requester's, and opening somebody's organisation is still a 404.
`test_instance_admin_is_a_table_not_a_column` asserts the absence by reading
that module's source, exactly as the `disabled_at` test already does. The
e2e suite proves the live half: the panel can *count* an organisation's
tasks and cannot *open* it.

**3. Metadata only.** Counts, dates and names, never a task title, a comment,
a private note or a file. Not squeamishness: this product makes promises a
browsing backoffice would quietly void. An organisation's *name* is the one
judgement call, included because a name is what a spam organisation is
recognised by.

**Still no staff tier — and `instance_admins` being a table rather than a
column is the whole reason that is still true.** `users` has no `role`,
`kind` or `is_admin` column and `test_a_user_has_no_role_or_kind_column`
fails the build if one appears, because what a person may do *inside* an
organisation must come from their membership and their grants, with no second
place to look. An instance admin doesn't answer that question at all. It sits
on the same side of the same line as `users.disabled_at`: upstream of the
access model, saying nothing about what a working account may do in a working
organisation.

**Suspension is two mechanisms for an account, and one for an
organisation.**

- **An account** — the front door is `sign_in_post`, overridden in
  `security/authn.py` to answer `SIGN_IN_NOT_ALLOWED`, checked *before* the
  password is verified so a suspended account can't be used as an oracle for
  whether a password is right. The open tab is `set_disabled`'s caller
  revoking every live session through SuperTokens, which owns them. In
  practice that is what fires, and the suite asserts **401**, not 403: the
  session is gone, so the request never reaches a route. `deps.py`'s own 403
  is defence in depth behind it. Asserting 403 there would be asserting the
  weaker path and calling the real one a failure — which is how the first
  version of the test read.
- **An organisation** — `organisations.suspended_at`, enforced in exactly one
  place: `organisations.context_for`, upstream of every visibility
  expression. **403, not 404**, unlike an organisation you were never in: the
  member *is* a member, it *is* there, and it is coming back, so telling them
  it vanished would send them to support believing they had been removed. No
  sessions are revoked either — the people in it may be perfectly legitimate
  members of other organisations, and signing them out of the product would
  be punishing them for it.

**A suspended organisation stays in your list rather than disappearing, and
`App.tsx` says why.** `OrganisationOut` carries `suspended`/
`suspended_reason`, and the shell renders `SuspendedOrg` in place of the
whole screen — the same wholesale replacement `MfaGate` and `VerifyEmailGate`
already do, and for the same reason: without it every panel on the page fails
its own fetch with a 403 and the person is looking at an empty screen with no
explanation. The operator's reason is the most useful sentence there, so it
is the one in the largest type.

**"Last active" is derived, never stamped.** There is no `last_seen_at`
column, deliberately: keeping one accurate costs a write on the request hot
path for every signed-in person. `_last_active()` is instead the newest of
the things somebody actually *did* — a task event, a time entry, a comment, a
sign-in — as four correlated `MAX`es under one `GREATEST` (which skips NULLs,
so "signed up and did nothing" is a real NULL rather than an epoch date). The
caveat worth knowing before reading it as "last seen": **somebody who only
reads looks idle.** For abuse triage that bias is right, since the thing being
looked for is people generating volume. An organisation's own last activity
is one subquery instead — `MAX(tasks.updated_at)`, which is "last activity"
by this product's own definition rather than "last row update", since a
comment, a file, a tag or an hour logged all stamp it through
`tasks_service.announce()`.

**The local `users` row is created lazily, and for this tool that is the
target population rather than an edge case.** It appears on somebody's first
authenticated request, so an account that signed up and walked away has no row
at all — precisely what a registration script produces. `suspend` and
`grant-admin` therefore fall back to asking SuperTokens and materialise the
row through `users_service.get_or_create`, so there is somewhere to record
the fact. Deliberately **not** done for `users`/`orgs`: inventing rows as a
side effect of *listing* would make the totals disagree with themselves
between runs.

**Ordering matters in `suspend`.** The flag is committed before sessions are
revoked — the other way round, a revoked session just sends them to the
sign-in screen and straight back in.

**You cannot suspend yourself from the panel**, and it is the one guard in
`api/routers/instance.py` that isn't about who may reach the surface. Locking
yourself out of the panel you are standing in is recoverable only from a
shell you might not have to hand. Suspending a *different* instance admin is
allowed — that is a real thing an operator may need to do, and the shell is
the backstop either way.

**The front door is the operator's, and it is the one thing here that
changes what a signed-out stranger sees.** `instance_settings` — one row,
ever — carries the landing page's heading and whether registration is open.
Both are in the panel's Front door card, both are in
`scripts/instance.sh` (`settings`, `headline`, `open-signups`,
`close-signups`), one service behind both as usual.

- **A table, not `core/config.py`.** Everything else configurable about an
  installation needs a restart, which is right for a database URL and wrong
  for a switch an operator reaches for during a spam wave. And not a
  `VITE_*` variable either: the frontend bundle carries no build-time
  configuration at all, so one built image runs on any domain.
- **A singleton enforced by the database**, `uq_instance_settings_singleton`
  — a unique index on the constant `(true)`. `settings()` creates the row on
  first read and relies on that index failing rather than on a lock, because
  the read that creates it is the landing page's.
- **The row is read publicly**, `GET /api/public/settings`
  (`api/routers/public.py`), because the page that renders it is reached
  with no session. Writing is the panel's `PUT /instance/settings`, 404 for
  everybody else like the rest of the surface. There is deliberately no
  `GET /instance/settings`: a second route answering the same two fields is
  a second thing to keep in step.
- **It stays inside the three rules above.** It appoints nobody, reads
  nobody's content, and closing registration takes no access from anyone who
  already has an account.

**Closing registration does not close it on the people you invited**, and
`signup_allowed_for` is the one place that rule is written. A closed
installation still admits an address with an outstanding `invited` row —
otherwise the switch would lock out exactly the people the operator named,
since somebody invited with no account yet has no route in but sign-up. The
consequence worth knowing: an invite *link* is normally bearer authority
(`services/invites.py`: whoever holds the token joins, regardless of the
address it was sent to), and with signups closed that stops being true for
somebody who has no account yet, because they meet the address check first.
That is a tightening rather than a bug — an operator who closes the door is
asking for "only the people I named" — and `scripts/e2e-instance.sh` pins
both halves: a stranger refused, an invited address through.

**The frontend hiding a button is never the gate.** `security/authn.py`'s
`sign_up_post` override is, shaped exactly like the `sign_in_post`
suspension refusal beside it — a typed `SignUpPostNotAllowedResponse`
carrying a sentence the person can act on. Note the one asymmetry between
the two: a database error in the suspension check falls back to *letting the
sign-in proceed* (the alternative is locking out the whole instance, and
`CurrentUser` refuses a suspended account anyway), and a database error in
this one falls back to *open* for the same style of reason — there is no
second line of defence here, and refusing every sign-up on a transient error
would look exactly like the product being broken.

**Prevention beats cleanup, and both front doors say so.** A signup rate well
ahead of the organisations-created rate is the shape spam takes here:
accounts are cheap to make, and creating an organisation is the first thing a
real person does next. `signups_outpacing_organisations` is resolved
server-side so the CLI's note and the panel's banner cannot disagree. If that
reading is routine, the gate is open too wide — closing signup or enforcing
`EMAIL_VERIFICATION` is cheaper than suspending people weekly.

**A trap worth not repeating.** `AccountInfoInput` is in
`supertokens_python.types.base`, not `supertokens_python.types` — guessed
wrong first, and the failure was swallowed by the broad `except` that keeps
an unreachable core from being fatal, so it reported "no account matching"
rather than an import error. Confirm an SDK symbol against the installed
package, the same rule the MCP section already states.

**A second trap, found by a browser test and worth more than it looks.** The
panel's suspend dialog originally stayed mounted and cleared its fields in an
effect keyed on the target — and the target was a fresh object literal on
every parent render, so the effect refired and wiped the reason somebody had
just typed. The suspension landed with no note at all, which on *this* screen
means an irreversible-looking action with nothing for the next person to
review. The fix is the same one the changelog's own add dialog uses: mount
one per target, keyed by its id, and initialise state at mount rather than
resetting it in an effect. **An effect whose dependency is built inline in
JSX fires on every render of the parent**, and there is no warning anywhere.
