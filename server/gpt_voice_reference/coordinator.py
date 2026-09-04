"""A small coordinator hiding the Voice Agent control-loop complexity."""

from __future__ import annotations

from server.gpt_voice_reference.models import (
    CallTool,
    ConversationItem,
    DelegateTask,
    EndSession,
    RequireConfirmation,
    Speak,
    VoiceEvent,
    VoiceSnapshot,
)
from server.gpt_voice_reference.ports import RealtimeSession, ToolExecutor, WorkerManager


class OpenRealtime:
    def __init__(
        self,
        *,
        realtime: RealtimeSession,
        tools: ToolExecutor | None = None,
        workers: WorkerManager | None = None,
    ) -> None:
        self._realtime = realtime
        self._tools = tools
        self._workers = workers
        self._items: list[ConversationItem] = []
        self._active_tool_calls: set[str] = set()
        self._active_workers: dict[str, str] = {}
        self._pending_confirmation: str | None = None
        self._output_active = False
        self._generation = 0
        self._phase = "active"

    async def submit_turn(self, text: str) -> list[VoiceEvent]:
        if self._phase != "active":
            raise RuntimeError("Voice session is closed")
        self._items.append(ConversationItem(type="user", text=text))
        self._pending_confirmation = None
        return await self._drive_realtime()

    async def complete_worker(self, worker_id: str, *, result: str) -> list[VoiceEvent]:
        self._take_worker(worker_id)
        self._items.append(
            ConversationItem(type="worker_result", text=result, correlation_id=worker_id)
        )
        if self._phase != "active":
            return [
                VoiceEvent(
                    type="worker.completed",
                    text=result,
                    data={"worker_id": worker_id, "spoken": False},
                )
            ]
        events = [
            VoiceEvent(type="worker.completed", text=result, data={"worker_id": worker_id})
        ]
        events.extend(await self._drive_realtime())
        return events

    async def fail_worker(self, worker_id: str, *, error: str) -> list[VoiceEvent]:
        self._take_worker(worker_id)
        self._items.append(
            ConversationItem(type="worker_error", text=error, correlation_id=worker_id)
        )
        if self._phase != "active":
            return [
                VoiceEvent(
                    type="worker.failed",
                    text=error,
                    data={"worker_id": worker_id, "spoken": False},
                )
            ]
        events = [VoiceEvent(type="worker.failed", text=error, data={"worker_id": worker_id})]
        events.extend(await self._drive_realtime())
        return events

    async def cancel_worker(self, worker_id: str) -> list[VoiceEvent]:
        if worker_id not in self._active_workers:
            raise LookupError(f"Unknown or completed worker: {worker_id}")
        if self._workers is None:
            raise RuntimeError("No WorkerManager is configured")
        await self._workers.cancel(worker_id)
        self._active_workers.pop(worker_id)
        self._items.append(
            ConversationItem(type="worker_cancelled", text="cancelled", correlation_id=worker_id)
        )
        return [VoiceEvent(type="worker.cancelled", data={"worker_id": worker_id})]

    def _take_worker(self, worker_id: str) -> None:
        try:
            self._active_workers.pop(worker_id)
        except KeyError as error:
            raise LookupError(f"Unknown or completed worker: {worker_id}") from error

    async def interrupt_output(self) -> list[VoiceEvent]:
        if not self._output_active:
            return []
        await self._realtime.cancel_output()
        self._output_active = False
        self._generation += 1
        return [VoiceEvent(type="response.cancelled", data={"generation": self._generation})]

    def mark_output_finished(self) -> None:
        """Record the transport/player's end-of-playback notification."""
        self._output_active = False

    async def _drive_realtime(self) -> list[VoiceEvent]:
        events: list[VoiceEvent] = []
        for _ in range(8):
            action = await self._realtime.next_action(tuple(self._items))
            if isinstance(action, Speak):
                self._items.append(ConversationItem(type="assistant", text=action.text))
                self._output_active = True
                events.append(VoiceEvent(type="speech.requested", text=action.text))
                return events
            if isinstance(action, CallTool):
                if self._tools is None:
                    raise RuntimeError(
                        "Realtime requested a tool but no ToolExecutor is configured"
                    )
                self._active_tool_calls.add(action.call_id)
                events.append(
                    VoiceEvent(
                        type="tool.started",
                        data={"call_id": action.call_id, "name": action.name},
                    )
                )
                try:
                    result = await self._tools.execute(action.name, action.arguments)
                except Exception as error:
                    self._active_tool_calls.discard(action.call_id)
                    message = str(error) or type(error).__name__
                    self._items.append(
                        ConversationItem(
                            type="tool_error",
                            text=message,
                            correlation_id=action.call_id,
                        )
                    )
                    events.append(
                        VoiceEvent(
                            type="tool.failed",
                            text=message,
                            data={"call_id": action.call_id, "name": action.name},
                        )
                    )
                    continue
                self._active_tool_calls.discard(action.call_id)
                self._items.append(
                    ConversationItem(
                        type="tool_result",
                        text=result,
                        correlation_id=action.call_id,
                    )
                )
                events.append(
                    VoiceEvent(
                        type="tool.completed",
                        text=result,
                        data={"call_id": action.call_id, "name": action.name},
                    )
                )
                continue
            if isinstance(action, DelegateTask):
                if self._workers is None:
                    raise RuntimeError(
                        "Realtime requested delegation but no WorkerManager is configured"
                    )
                worker_id = await self._workers.start(action.task)
                self._active_workers[worker_id] = action.task
                self._items.append(
                    ConversationItem(
                        type="assistant",
                        text=action.acknowledgement,
                        correlation_id=worker_id,
                    )
                )
                self._output_active = True
                events.extend(
                    [
                        VoiceEvent(type="speech.requested", text=action.acknowledgement),
                        VoiceEvent(
                            type="worker.started",
                            data={"worker_id": worker_id, "task": action.task},
                        ),
                    ]
                )
                return events
            if isinstance(action, RequireConfirmation):
                self._pending_confirmation = action.confirmation_id
                self._items.append(
                    ConversationItem(
                        type="assistant",
                        text=action.prompt,
                        correlation_id=action.confirmation_id,
                    )
                )
                self._output_active = True
                events.extend(
                    [
                        VoiceEvent(type="speech.requested", text=action.prompt),
                        VoiceEvent(
                            type="confirmation.required",
                            text=action.prompt,
                            data={"confirmation_id": action.confirmation_id},
                        ),
                    ]
                )
                return events
            if isinstance(action, EndSession):
                self._phase = "closed"
                self._output_active = False
                events.append(VoiceEvent(type="session.ended", data={"reason": action.reason}))
                return events
            raise TypeError(f"Unsupported Realtime action: {type(action).__name__}")
        raise RuntimeError("Realtime action loop exceeded 8 steps")

    def snapshot(self) -> VoiceSnapshot:
        return VoiceSnapshot(
            items=tuple(self._items),
            active_tool_calls=tuple(sorted(self._active_tool_calls)),
            active_workers=tuple(sorted(self._active_workers)),
            pending_confirmation=self._pending_confirmation,
            output_active=self._output_active,
            generation=self._generation,
            phase=self._phase,
        )


# Preserve direct imports from this module across the product rename.
VoiceAgent = OpenRealtime
