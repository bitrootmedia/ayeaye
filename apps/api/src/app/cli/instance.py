"""The instance operator's command line. See `services/instance.py` first.

Run through `scripts/instance.sh`. There is a web panel onto the same service
now (`/instance`, `api/routers/instance.py`), and this is the other front
door — but **granting the `instance_admins` row is shell-only and stays that
way**, because a panel that can appoint its own successors turns one stolen
session into a permanent foothold. See that service's docstring.

Output is plain aligned text rather than a table library: this is read in an
SSH session on somebody's phone as often as on a laptop, and it should also
survive being piped into `grep`.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from app.db import SessionLocal
from app.services import instance as instance_service


def _ago(when: datetime | None) -> str:
    if when is None:
        return "—"
    delta = datetime.now(UTC) - when
    days = delta.days
    if days > 0:
        return f"{days}d"
    hours = delta.seconds // 3600
    if hours > 0:
        return f"{hours}h"
    return f"{delta.seconds // 60}m"


def _clip(text: str | None, width: int) -> str:
    text = text or "—"
    return text if len(text) <= width else text[: width - 1] + "…"


async def _stats() -> None:
    async with SessionLocal() as db:
        t = await instance_service.totals(db)
    print(f"  accounts        {t.users:>8}   ({t.users_last_24h} in the last 24h)")
    print(f"  suspended       {t.disabled_users:>8}")
    print(f"  organisations   {t.organisations:>8}   ({t.organisations_last_24h} in the last 24h)")
    print(f"  tasks           {t.tasks:>8}")
    # A signup rate far above the organisation rate is the shape spam takes
    # here: accounts are cheap to make, and an organisation is the first
    # thing a real person does next.
    if t.users_last_24h > 20 and t.users_last_24h > t.organisations_last_24h * 3:
        print()
        print("  note: signups are well ahead of organisations created — worth a look")


async def _users(args: argparse.Namespace) -> None:
    async with SessionLocal() as db:
        rows, total = await instance_service.list_users(
            db, limit=args.limit, offset=args.offset, newest_first=not args.oldest
        )
    print(f"  {'EMAIL':42} {'JOINED':>7} {'ORGS':>5} {'TASKS':>6}  STATE")
    for r in rows:
        state = "suspended" if r.disabled_at else ""
        if r.disabled_at and r.disabled_reason:
            state = f"suspended — {_clip(r.disabled_reason, 40)}"
        print(
            f"  {_clip(r.email, 42):42} {_ago(r.created_at):>7} "
            f"{r.organisations:>5} {r.tasks:>6}  {state}"
        )
    _footer(len(rows), total, args.offset)


async def _orgs(args: argparse.Namespace) -> None:
    async with SessionLocal() as db:
        rows, total = await instance_service.list_organisations(
            db, limit=args.limit, offset=args.offset, newest_first=not args.oldest
        )
    print(f"  {'NAME':32} {'OWNER':38} {'MADE':>6} {'PEOPLE':>7} {'TASKS':>6}")
    for r in rows:
        print(
            f"  {_clip(r.name, 32):32} {_clip(r.owner_email, 38):38} "
            f"{_ago(r.created_at):>6} {r.members:>7} {r.tasks:>6}"
        )
    _footer(len(rows), total, args.offset)


def _footer(shown: int, total: int, offset: int) -> None:
    """Always says what the page is a page *of* — the same rule the task
    list's own pager follows, and the reason there is no silent cap."""
    print()
    end = offset + shown
    print(f"  showing {offset + 1 if shown else 0}–{end} of {total}")
    if end < total:
        print(f"  next: --offset {end}")


async def _suspend(args: argparse.Namespace, *, disabled: bool) -> None:
    async with SessionLocal() as db:
        user = await instance_service.find_user(db, args.who)
        if user is None and disabled:
            # **The local `users` row is created lazily**, on somebody's
            # first authenticated request — so an account that signed up and
            # never actually used the app has no row here at all. That is
            # not an edge case for this command, it is the target
            # population: a script that registers four hundred addresses and
            # walks away produces exactly that. Ask SuperTokens, which owns
            # identity and knew about them the moment they signed up, and
            # materialise the row so there is somewhere to record the
            # suspension.
            user = await _adopt_from_supertokens(db, args.who)
        if user is None:
            print(f"no account matching {args.who!r}", file=sys.stderr)
            if disabled:
                print("(checked this installation's own records and SuperTokens)", file=sys.stderr)
            raise SystemExit(1)

        changed = await instance_service.set_disabled(
            db, user, disabled=disabled, reason=getattr(args, "reason", None)
        )
        if not changed:
            print(f"{user.email} is already {'suspended' if disabled else 'active'}")
            return

        if disabled:
            # Order matters: the flag is committed above, so a session
            # revoked here cannot be replaced by signing straight back in.
            # Shared with the panel's own route rather than duplicated —
            # see `services/instance.py::revoke_sessions`.
            revoked = await instance_service.revoke_sessions(user.supertokens_user_id)
            print(f"suspended {user.email} — {revoked} session(s) revoked")
            print("they can no longer sign in, and their data is untouched")
        else:
            print(f"restored {user.email} — they can sign in again")


async def _adopt_from_supertokens(db, who: str):
    """Create the local row for an account SuperTokens knows and we don't.

    Only reached from `suspend`, deliberately — `users` and `orgs` report
    what this installation actually holds, and quietly inventing rows as a
    side effect of *listing* would make the totals disagree with themselves
    between runs. Suspending is different: the row is the place the
    suspension lives, so it has to exist.

    Reuses `users_service.get_or_create` rather than inserting here, so
    there stays exactly one way a local user row comes into being.
    """
    if "@" not in who:  # a bare id can't be looked up by email
        return None
    try:
        from supertokens_python.asyncio import list_users_by_account_info
        from supertokens_python.types.base import AccountInfoInput

        from app.security.authn import init_auth
        from app.services import users as users_service

        init_auth()
        found = await list_users_by_account_info(
            "public", AccountInfoInput(email=who.strip().lower())
        )
        if not found:
            return None
        return await users_service.get_or_create(db, supertokens_user_id=found[0].id)
    except Exception as exc:  # pragma: no cover - depends on a live core
        print(f"warning: could not ask SuperTokens about {who} ({exc})", file=sys.stderr)
        return None


async def _suspend_org(args: argparse.Namespace, *, suspended: bool) -> None:
    """Lock or unlock a whole organisation.

    No sessions are revoked, unlike suspending an account: its members may be
    perfectly legitimate members of other organisations, and signing them out
    of the product would be punishing them for it.
    """
    async with SessionLocal() as db:
        org = await instance_service.find_organisation(db, args.which)
        if org is None:
            print(f"no organisation matching {args.which!r}", file=sys.stderr)
            print("(give the slug or the id — names are not unique)", file=sys.stderr)
            raise SystemExit(1)
        changed = await instance_service.set_organisation_suspended(
            db, org, suspended=suspended, reason=getattr(args, "reason", None)
        )
        if not changed:
            print(f"{org.slug} is already {'suspended' if suspended else 'active'}")
            return
        if suspended:
            print(f"suspended {org.slug} — its members are locked out and told why")
            print("nothing was deleted; `restore-org` puts everybody straight back")
        else:
            print(f"restored {org.slug} — its members are back exactly where they were")


async def _admins() -> None:
    async with SessionLocal() as db:
        rows = await instance_service.list_admins(db)
    if not rows:
        print("  no instance admins — grant one with: instance.sh grant-admin <email>")
        return
    print(f"  {'EMAIL':42} {'SINCE':>6}  NOTE")
    for user, admin in rows:
        print(f"  {_clip(user.email, 42):42} {_ago(admin.created_at):>6}  {_clip(admin.note, 40)}")


async def _set_admin(args: argparse.Namespace, *, grant: bool) -> None:
    """Grant or revoke the instance-admin row.

    **Deliberately shell-only**, which is the whole reason the web panel is
    acceptable at all: it cannot appoint its own successors, so one stolen
    session is not a permanent foothold. See `models/instance_admin.py`.
    """
    async with SessionLocal() as db:
        user = await instance_service.find_user(db, args.who)
        if user is None and grant:
            # Same reasoning as `suspend`: the local row is created lazily on
            # somebody's first authenticated request, so an account that
            # signed up and hasn't used the app yet has none to attach this
            # to. Ask SuperTokens and materialise it.
            user = await _adopt_from_supertokens(db, args.who)
        if user is None:
            print(f"no account matching {args.who!r}", file=sys.stderr)
            raise SystemExit(1)
        if grant:
            changed = await instance_service.grant_admin(db, user, note=args.note)
            if changed:
                print(f"{user.email} is now an instance admin")
                print("they will see an Instance item in the rail on their next page load")
            else:
                print(f"{user.email} already is one")
        else:
            changed = await instance_service.revoke_admin(db, user)
            print(
                f"{user.email} is no longer an instance admin"
                if changed
                else f"{user.email} wasn't one"
            )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="instance", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="totals for the whole installation")

    for name, help_text in (("users", "list accounts"), ("orgs", "list organisations")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--limit", type=int, default=25)
        p.add_argument("--offset", type=int, default=0)
        p.add_argument("--oldest", action="store_true", help="oldest first (default: newest)")

    p = sub.add_parser("suspend", help="stop an account signing in")
    p.add_argument("who", help="email address or user id")
    p.add_argument("--reason", help="a note for whoever reviews this later")

    p = sub.add_parser("restore", help="let a suspended account back in")
    p.add_argument("who", help="email address or user id")

    p = sub.add_parser("suspend-org", help="lock a whole organisation")
    p.add_argument("which", help="slug or organisation id")
    p.add_argument("--reason", help="shown to its members when they try to open it")

    p = sub.add_parser("restore-org", help="unlock a suspended organisation")
    p.add_argument("which", help="slug or organisation id")

    sub.add_parser("admins", help="who administers this installation")

    p = sub.add_parser("grant-admin", help="give somebody the instance panel")
    p.add_argument("who", help="email address or user id")
    p.add_argument("--note", help="why, for whoever reads this list later")

    p = sub.add_parser("revoke-admin", help="take the instance panel away")
    p.add_argument("who", help="email address or user id")

    args = parser.parse_args(argv)
    if args.command == "stats":
        asyncio.run(_stats())
    elif args.command == "users":
        asyncio.run(_users(args))
    elif args.command == "orgs":
        asyncio.run(_orgs(args))
    elif args.command == "suspend":
        asyncio.run(_suspend(args, disabled=True))
    elif args.command == "restore":
        asyncio.run(_suspend(args, disabled=False))
    elif args.command == "suspend-org":
        asyncio.run(_suspend_org(args, suspended=True))
    elif args.command == "restore-org":
        asyncio.run(_suspend_org(args, suspended=False))
    elif args.command == "admins":
        asyncio.run(_admins())
    elif args.command == "grant-admin":
        asyncio.run(_set_admin(args, grant=True))
    elif args.command == "revoke-admin":
        asyncio.run(_set_admin(args, grant=False))


if __name__ == "__main__":
    main()
