"""Own Artifact IO through caller cancellation; never fake SDK worker exit."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from server.artifacts.protocol import ArtifactConflict, ArtifactRecord


class ArtifactUploadOwner:
    """A bounded task owner, with no worker queue or independent state actor."""

    def __init__(self) -> None:
        self.tasks: set[asyncio.Task[ArtifactRecord]] = set()

    async def run(
        self, operation: Callable[[], Coroutine[Any, Any, ArtifactRecord]]
    ) -> ArtifactRecord:
        if len(self.tasks) >= 64:
            raise ArtifactConflict("artifact upload capacity is exhausted")
        task = asyncio.create_task(operation(), name="artifact-upload")
        self.tasks.add(task)
        task.add_done_callback(self._finished)
        return await asyncio.shield(task)

    def _finished(self, task: asyncio.Task[ArtifactRecord]) -> None:
        self.tasks.discard(task)
        if not task.cancelled():
            task.exception()
