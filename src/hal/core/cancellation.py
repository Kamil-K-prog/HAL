from __future__ import annotations

import contextlib
from asyncio import AbstractEventLoop, Event, get_running_loop
from collections.abc import Callable
from threading import Lock
from typing import Any

from hal.core.errors import HalCancellationError


class CancellationToken:
    def __init__(self) -> None:
        self._lock = Lock()
        self._is_cancelled: bool = False
        self._reason: str | None = None
        self._callbacks: list[Callable[[], Any]] = []
        self._waiters: list[tuple[AbstractEventLoop, Event]] = []

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._is_cancelled

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason

    def cancel(self, reason: str | None = None) -> bool:
        with self._lock:
            if self._is_cancelled:
                return False
            self._is_cancelled = True
            self._reason = reason

            waiters = list(self._waiters)
            callbacks = list(self._callbacks)
            self._waiters.clear()
            self._callbacks.clear()

        for loop, event in waiters:
            if not loop.is_closed():
                loop.call_soon_threadsafe(event.set)

        exceptions = []
        for cb in callbacks:
            try:
                cb()
            except Exception as e:
                exceptions.append(e)

        if exceptions:
            raise ExceptionGroup("Callbacks exceptions", exceptions)
        return True

    def raise_if_cancelled(self) -> None:
        with self._lock:
            if self._is_cancelled:
                raise HalCancellationError(
                    user_message=self._reason
                )
            return

    def on_cancel(self, callback: Callable[[], Any]) -> Callable[[], None]:
        should_call_immediately = False
        with self._lock:
            if self._is_cancelled:
                should_call_immediately = True
            else:
                def unsubscribe() -> None:
                    with self._lock, contextlib.suppress(ValueError):
                        self._callbacks.remove(callback)

                self._callbacks.append(callback)
                return unsubscribe

        if should_call_immediately:
            callback()
        return lambda: None

    def create_child(self) -> CancellationToken:
        child = CancellationToken()
        with self._lock:
            if self._is_cancelled:
                child.cancel(self._reason)
                return child
        unsubscribe = self.on_cancel(lambda: child.cancel(self._reason))
        child.on_cancel(unsubscribe)
        return child

    async def wait(self) -> str | None:
        loop = get_running_loop()
        event = Event()

        with self._lock:
            if self._is_cancelled:
                return self._reason
            item = (loop, event)
            self._waiters.append(item)

        try:
            await event.wait()
        finally:
            with self._lock:
                if not self._is_cancelled and item in self._waiters:
                    self._waiters.remove(item)

        return self.reason