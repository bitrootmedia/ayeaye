"""The single /api router tree.

Everything the browser calls lives under /api on one origin, alongside
SuperTokens' own /api/auth routes (served by its middleware). Adding a resource
means adding a module in routers/ and one include_router line here.
"""

from fastapi import APIRouter

from app.api.routers import (
    calendar,
    conversations,
    dashboard,
    invites,
    notifications,
    organisations,
    planner,
    reminders,
    structure,
    tasks,
    time,
    users,
)

api_router = APIRouter()

api_router.include_router(users.router)

# One inbox per person, not scoped to an organisation.
api_router.include_router(notifications.router)

# The running timer is per person and global — one per human across the whole
# installation — so it sits under /me alongside the inbox.
api_router.include_router(time.me_router)

# Reminders. Personal, so reading them is cross-organisation like the inbox —
# but setting one needs a task, so that half is organisation-scoped. Both
# halves live in the one module.
api_router.include_router(reminders.router)

# The organisation's landing screen — announcements and who's away — plus the
# personal out-of-office that feeds it.
api_router.include_router(dashboard.router)

# The tenancy boundary: everything else hangs off an organisation.
api_router.include_router(organisations.router)

# Teams, project groups and projects — all organisation-scoped, all resolving
# visibility through services/access.py.
api_router.include_router(structure.router)

# Tasks, their history and their per-task grants. Same organisation prefix.
api_router.include_router(tasks.router)

# Time logged against those tasks, plus the rollups.
api_router.include_router(time.router)

# A personal day plan over the tasks a person can see. Organisation-scoped
# like Tasks; the admin escape hatch is time entries' shape, not notes' —
# see services/planner.py.
api_router.include_router(planner.router)

# Every visible task's due date, team-wide, plus the caller's own reminders.
# Organisation-scoped like Tasks and Planner — see the router's own docstring
# for why the two halves have different visibility rules.
api_router.include_router(calendar.router)

# Comment threads on tasks and projects. There is no separate comment system —
# these ARE the conversations, which is what makes attachments, voice notes and
# the unread badge one implementation instead of two.
api_router.include_router(conversations.router)

# The realtime socket. Authenticated by the session cookie, which single-origin
# gives us for free — see the route docstring.
api_router.include_router(conversations.ws_router)

# Joining one. Deliberately NOT under /organisations/{id} — you aren't a member
# yet, so the membership dependency there would 404 you out of your own invite.
api_router.include_router(invites.router)
