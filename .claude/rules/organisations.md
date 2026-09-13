---
paths:
  - "apps/api/src/app/services/organisations.py"
  - "apps/api/src/app/services/invites.py"
  - "apps/api/src/app/models/organisation.py"
  - "apps/api/src/app/api/routers/organisations.py"
  - "apps/api/src/app/api/routers/invites.py"
  - "apps/web/src/views/Organisation*.tsx"
  - "apps/web/src/views/OrganisationDetail.tsx"
  - "apps/web/src/views/AcceptInvite.tsx"
  - "scripts/e2e-organisations.sh"
---

# Organisations, membership, invites and settings

## Organisations and membership

Read the `services/organisations.py` docstring before touching any of this. The
four rules there — creator owns it, you only grant what you hold, you can't act
on someone above you, the last owner can't leave — are tested exhaustively in
`tests/test_organisation_rules.py` as **pure functions with no database**. That
file is the template for the Phase 3 access matrix.

Two structural choices worth not undoing:

**Membership and invitations are one table.** `organisation_members` holds both;
the difference is `status`. Binding an invitation at signup is then one UPDATE
rather than a copy between tables with a window in the middle. The model
docstring has the four legal row shapes and the CHECK constraints that allow
exactly those — `invited`, `active`, and now `disabled`.

**Disabling a member reuses `context_for`'s own gate rather than adding a
second check.** `context_for` only ever resolves an `active` membership; a
`disabled` row just stops matching it, so every organisation-scoped route
404s for that person from the next request on, with nothing else anywhere
in the codebase that needs to know the status exists. `disable_member`/
`enable_member` (`services/organisations.py`) reuse rules 2 through 4
exactly as written — rank, and the last-owner check — rather than
introducing a fifth rule. **Deliberately not `remove_member` in miniature**:
removal reassigns every project and task the person owns, because the row
is about to stop existing and a thing with no owner is a thing nobody can
administer. Disabling is a pause, not a departure — their work stays
exactly where it was, for the admin who re-enables them to find again.

**No separate self-block, on purpose.** `remove_member` already lets you act
on yourself (that's how leaving works), protected only by the last-owner
rule. Disabling copies that shape rather than inventing a "you can't disable
yourself" rule that doesn't exist anywhere else in this module: a plain
admin can disable their own access same as they could leave outright, and a
lone owner disabling themselves is caught by the ordinary last-owner check,
not a bespoke one.

**An invitation never joins anyone automatically.** Signing up with an invited
address *attaches* the invitation (`user_id` set, still `invited`) and it
appears in `GET /me/invites` for the person to accept. The reference project
bound shares outright and then listed the consequence in its own known-problems
section: anyone who knows your email can drop something into your account. One
click closes that.

The exception is the invite link, where **opening it is the consent** and it
activates immediately. The trade that comes with it is written out in the
`services/invites.py` docstring: the token is the authority, so whoever holds
it joins regardless of the address it was sent to. Mitigated by being
single-use, revocable, and 256 bits — and reversible in one condition if it
ever stops being an acceptable trade.

Two rules that only exist in SQL, so they're easy to lose in a migration:

- **`uq_org_members_org_user`** is partial (`WHERE user_id IS NOT NULL`).
  Without the partial clause, several invitations to people who don't have
  accounts yet would collide on NULL.
- **`uq_org_members_org_invited_email`** is scoped to `status = 'invited'`, so
  re-inviting someone who left doesn't collide with their historical row. This
  is also why removal is a hard DELETE rather than a `revoked` status.

`bind_pending_for_user` has a `NOT EXISTS` guard that is load-bearing: without
it, someone already in an organisation who also has an outstanding invitation
to it violates the unique index, and it fails **their first authenticated
request** with a 500 — the single worst place for it.

## Organisation settings, and where the data export lives

`/orgs/{id}/settings` — its own screen, with its own gear icon in the rail,
`views/OrganisationSettings.tsx`. It didn't start that way: rename, the
two-factor requirement, deletion and `ExportCard` were all a second,
unrelated card at the bottom of `/people`, because that screen already
existed when data export shipped and nobody had asked for a settings screen
yet. The result was a genuine discoverability bug — a real "take your data"
button existed from the day exports landed, and the only way to find it was
to scroll past the entire member roster on a page whose own nav label is
"People." Moved out once it was reported.

**`ExportCard` is visible to every member, not gated on the same role check
as the rest of the page.** A data export is scoped to the requester's own
visibility (`services/exports.py`'s own "no branch that grants anybody else
access" rule), not an admin privilege — a plain member exporting their own
view of the organisation is exactly the intended use, so the card renders
unconditionally while the rename/MFA/delete card beneath it stays gated on
`canRename` / `canRequireMfa` / `canDeleteOrg`, precisely as it was on the
People page. `screenshots.spec.ts` photographs the new screen in both
themes (`03b-organisation-settings`, `17-organisation-settings-dark`).

## Slugs

- **Slugs are global and never follow a rename.** They're in URLs people have
  bookmarked, so renaming changes the label only. It also means a test that
  asserts a literal slug will drift as the database accumulates rows — see the
  per-run name in `scripts/e2e-organisations.sh`.
