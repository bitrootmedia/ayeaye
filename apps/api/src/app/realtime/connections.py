"""In-process registry of open WebSockets.

One instance per API process. With several uvicorn workers each process holds
only its own sockets, which is exactly why fan-out goes through Redis pub/sub:
every worker receives the event and forwards it to whichever browsers it
happens to be holding.

There is deliberately **no "watcher" concept** — the reference project had one
so a backoffice could see every job event, and nothing here has any business
reading a conversation it wasn't a party to. Dispatch is always to an explicit
list of people.
"""

import logging

from fastapi import WebSocket

logger = logging.getLogger("app.realtime")


class ConnectionManager:
    """Sockets by person, and by what each one is currently watching.

    Two registries because there are two genuinely different audiences, and
    conflating them was a bug:

    * **by user** — who should be *told* something happened. A small,
      stake-holding set: the owner, whoever must act, people who have spoken.
    * **by watch key** — who currently has a thread *open*. A read-only
      colleague reading along has no stake worth notifying about, but their
      screen must still update while they're looking at it.

    Watch keys are verified against the access model when the client asks to
    watch, not when an event is dispatched. That is safe because the event
    carries no content: if access was revoked in between, the refetch it
    triggers 404s, which is the correct outcome.
    """

    def __init__(self) -> None:
        # Keyed by our local user id — the same id everything else points at.
        self._by_user: dict[str, set[WebSocket]] = {}
        # "task:<uuid>" / "project:<uuid>" / "org:<uuid>" -> sockets with it
        # on screen. The org key is the board: it shows many tasks at once, so
        # watching each of them would be hundreds of registrations per tab.
        self._by_watch: dict[str, set[WebSocket]] = {}

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._by_user.setdefault(user_id, set()).add(ws)

    def watch(self, key: str, ws: WebSocket) -> None:
        """This socket now has that thread on screen.

        One at a time: opening a task replaces whatever was being watched, so
        a long session doesn't accumulate every thread the person visited.
        """
        self.unwatch_all(ws)
        self._by_watch.setdefault(key, set()).add(ws)

    def unwatch_all(self, ws: WebSocket) -> None:
        for key, sockets in list(self._by_watch.items()):
            sockets.discard(ws)
            if not sockets:
                self._by_watch.pop(key, None)

    def disconnect(self, user_id: str, ws: WebSocket) -> None:
        conns = self._by_user.get(user_id)
        if conns:
            conns.discard(ws)
            if not conns:
                self._by_user.pop(user_id, None)
        self.unwatch_all(ws)

    def is_connected(self, user_id: str) -> bool:
        return bool(self._by_user.get(user_id))

    async def dispatch(
        self, event: dict, *, user_ids: list[str], watch_keys: str | list[str] | None
    ) -> None:
        """Send to the people with a stake, plus anyone watching.

        Several keys, because one change has more than one audience: a task
        moving concerns the people with that task open **and** the people
        looking at a board it appears on. Same event, two registries, and a
        socket in both still receives it once — `targets` is a set.
        """
        targets: set[WebSocket] = set()
        for user_id in user_ids:
            targets |= set(self._by_user.get(user_id, ()))
        if isinstance(watch_keys, str):
            watch_keys = [watch_keys]
        for key in watch_keys or ():
            targets |= set(self._by_watch.get(key, ()))
        for ws in targets:
            try:
                await ws.send_json(event)
            except Exception:
                # A socket that died between the registry and the send. The
                # disconnect handler cleans it up; failing the dispatch for
                # everyone else would be worse.
                pass


# Process-wide singleton: the ws route registers sockets on it, and the Redis
# subscriber started in the lifespan dispatches to it.
manager = ConnectionManager()
