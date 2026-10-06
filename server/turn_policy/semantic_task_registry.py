"""Own async task families and request tokens; leave semantic decisions to the actor."""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


class SemanticTaskRegistry:
    def __init__(self) -> None:
        self.jobs: dict[str, asyncio.Task[None]] = {}
        self.all_tasks: set[asyncio.Task[None]] = set()
        self._requests: dict[str, str] = {}

    @staticmethod
    def _request_key(kind: str, chunk_id: str | None) -> str:
        return kind + (":" + chunk_id if chunk_id else "")

    def register(self, kind: str, chunk_id: str | None, token: str) -> None:
        self._requests[self._request_key(kind, chunk_id)] = token

    def accept(self, kind: str, chunk_id: str | None, token: str) -> bool:
        key = self._request_key(kind, chunk_id)
        if self._requests.get(key) != token:
            return False
        del self._requests[key]
        return True

    def start(self, key: str, operation: Coroutine[Any, Any, None]) -> None:
        previous = self.jobs.pop(key, None)
        if previous is not None:
            previous.cancel()
        task = asyncio.create_task(operation, name=f"turn-{key}")
        self.jobs[key] = task
        self.all_tasks.add(task)

        def finished(completed: asyncio.Task[None]) -> None:
            self.all_tasks.discard(completed)
            # Timer presence is actor state; only chunk execution records are disposable.
            # Its request token remains until the actor accepts or cancels the queued result.
            if (
                key.startswith(("endpoint_model:", "interruption_model:"))
                and self.jobs.get(key) is completed
            ):
                self.jobs.pop(key)

        task.add_done_callback(finished)

    def cancel(self, *families: str) -> None:
        for family in families:
            for key in tuple(self.jobs):
                if key != family and not key.startswith(family + ":"):
                    continue
                task = self.jobs.pop(key)
                task.cancel()
            name, separator, chunk_id = family.partition(":")
            request_kind = {
                "endpoint_model": "endpoint",
                "interruption_model": "interruption",
            }.get(name)
            if request_kind is not None:
                request_family = request_kind + (separator + chunk_id if separator else "")
                for key in tuple(self._requests):
                    if key == request_family or key.startswith(request_family + ":"):
                        self._requests.pop(key)

    def clear(self) -> None:
        self.cancel(*tuple(self.jobs))
        self._requests.clear()
