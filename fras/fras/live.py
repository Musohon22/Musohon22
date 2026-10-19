"""In-process pub/sub for the live dashboard feed (Server-Sent Events).

Handlers run in worker threads, so `publish` hands messages to the event loop
with call_soon_threadsafe. Channels are per tenant; subscribers filter by
scope on their side of the stream before sending.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict


class Broker:
    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def subscribe(self, channel: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs[channel].add(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue) -> None:
        self._subs[channel].discard(q)

    def _deliver(self, channel: str, message: dict) -> None:
        for q in list(self._subs.get(channel, ())):
            if q.full():
                try:
                    q.get_nowait()   # drop oldest; the UI reloads on gaps
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(message)

    def publish(self, channel: str, message: dict) -> None:
        if self.loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self._deliver(channel, message)
        else:
            self.loop.call_soon_threadsafe(self._deliver, channel, message)


broker = Broker()
