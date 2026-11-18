"""Local wakeups for durable jobs; SQLite remains the source of truth.

Subscribers register before reading the database and clear before each read,
so a commit between that read and waiting cannot be missed. Notifications may
come from worker threads. Other processes are covered by the polling timeout.
"""

import asyncio
import threading
from contextlib import asynccontextmanager


_lock = threading.Lock()
_subscribers = set()


class _Signal:
    def __init__(self, task_id):
        self.task_id = task_id
        self.loop = asyncio.get_running_loop()
        self.event = asyncio.Event()

    def clear(self):
        self.event.clear()

    async def wait(self, timeout=1.0):
        try:
            await asyncio.wait_for(self.event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False


@asynccontextmanager
async def subscribe(task_id=None):
    signal = _Signal(task_id)
    with _lock:
        _subscribers.add(signal)
    try:
        yield signal
    finally:
        with _lock:
            _subscribers.discard(signal)


def notify(task_id=None):
    """Wake matching task streams and schedulers, after a successful commit."""
    with _lock:
        subscribers = tuple(signal for signal in _subscribers
                            if task_id is None or signal.task_id in (None, task_id))
    for signal in subscribers:
        try:
            signal.loop.call_soon_threadsafe(signal.event.set)
        except RuntimeError:
            # A closing subscriber must not turn a successful DB write into an
            # application failure. Its next connection replays persisted events.
            if not signal.loop.is_closed():
                raise
