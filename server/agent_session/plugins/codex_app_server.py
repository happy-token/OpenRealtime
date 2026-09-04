"""Codex App Server conformer for the universal v2 Agent Driver Protocol.

The driver owns Codex protocol translation only. Task identity, deduplication,
backend selection, and durable recovery remain AgentTaskSupervisor concerns.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from server.agent_session.driver_protocol import (
    AgentCapability,
    AgentCapabilityDescriptor,
    AgentDriver,
    AgentEvent,
    AgentEventBase,
    AgentInput,
    AgentInputRequested,
    AgentMessageDelta,
    AgentPermissionRequested,
    AgentPlanUpdated,
    AgentProgressUpdated,
    AgentRunHandle,
    AgentRunLocator,
    AgentRunPhase,
    AgentRunSnapshot,
    AgentRunStarted,
    AgentRunTerminal,
    AgentStartRequest,
    AgentUsageUpdated,
    CancelResult,
    WorkspaceMode,
    utc_now,
)

JsonObject = dict[str, Any]
MessageHandler = Callable[[JsonObject], Awaitable[None]]


class CodexAppServerError(RuntimeError):
    """Base error for Codex App Server transport and protocol failures."""


class CodexRpcError(CodexAppServerError):
    def __init__(self, method: str, error: object) -> None:
        self.method = method
        self.error = error
        super().__init__(f"Codex App Server request {method!r} failed: {error}")


@dataclass(slots=True)
class _CodexRun:
    handle: AgentRunHandle
    phase: AgentRunPhase = AgentRunPhase.STARTING
    events: list[AgentEvent] = field(default_factory=list)
    response_parts: list[str] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    stream_error: BaseException | None = None
    ready_for_events: bool = False
    pending_messages: list[JsonObject] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    sequence_offset: int = 0


class _JsonlRpcClient:
    def __init__(
        self,
        command: Sequence[str],
        *,
        message_handler: MessageHandler,
        request_timeout_s: float,
    ) -> None:
        if not command:
            raise ValueError("Codex App Server command must be non-empty")
        self._command = tuple(command)
        self._message_handler = message_handler
        self._request_timeout_s = request_timeout_s
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[JsonObject]] = {}
        self._next_id = 1
        self._start_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._closed = False
        self._initialized = False
        self.stderr_tail: list[str] = []

    async def request(self, method: str, params: Mapping[str, Any]) -> JsonObject:
        await self._ensure_started()
        return await self._request_started(method, params)

    async def notify(self, method: str, params: Mapping[str, Any]) -> None:
        await self._ensure_started()
        await self._write({"method": method, "params": dict(params)})

    async def respond_error(self, request_id: object, message: str) -> None:
        await self._write(
            {
                "id": request_id,
                "error": {"code": -32001, "message": message},
            }
        )

    async def close(self) -> None:
        self._closed = True
        process = self._process
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                process.kill()
                await process.wait()
        tasks = tuple(task for task in (self._reader_task, self._stderr_task) if task is not None)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._fail_pending(CodexAppServerError("Codex App Server client closed"))
        self._process = None

    async def _ensure_started(self) -> None:
        if self._initialized:
            return
        async with self._start_lock:
            if self._initialized:
                return
            if self._closed:
                raise CodexAppServerError("Codex App Server client is closed")
            self._process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._reader_task = asyncio.create_task(
                self._read_loop(), name="codex-app-server-stdout"
            )
            self._stderr_task = asyncio.create_task(
                self._read_stderr(), name="codex-app-server-stderr"
            )
            await self._request_started(
                "initialize",
                {
                    "clientInfo": {
                        "name": "voice-agent",
                        "title": "Voice Agent",
                        "version": "0.1.0",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            await self._write({"method": "initialized", "params": {}})
            self._initialized = True

    async def _request_started(self, method: str, params: Mapping[str, Any]) -> JsonObject:
        loop = asyncio.get_running_loop()
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[JsonObject] = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._write({"method": method, "id": request_id, "params": dict(params)})
            response = await asyncio.wait_for(future, timeout=self._request_timeout_s)
        except BaseException:
            self._pending.pop(request_id, None)
            raise
        if "error" in response:
            raise CodexRpcError(method, response["error"])
        result = response.get("result", {})
        if not isinstance(result, dict):
            raise CodexAppServerError(
                f"Codex App Server returned a non-object result for {method!r}"
            )
        return result

    async def _write(self, message: JsonObject) -> None:
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None:
            raise CodexAppServerError("Codex App Server process is not running")
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        async with self._write_lock:
            process.stdin.write(encoded.encode("utf-8") + b"\n")
            await process.stdin.drain()

    async def _read_loop(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        failure: BaseException | None = None
        try:
            while line := await process.stdout.readline():
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as error:
                    raise CodexAppServerError(
                        f"Codex App Server emitted invalid JSONL: {error}"
                    ) from error
                if not isinstance(message, dict):
                    continue
                request_id = message.get("id")
                if request_id is not None and "method" not in message:
                    future = self._pending.pop(request_id, None)
                    if future is not None and not future.done():
                        future.set_result(message)
                    continue
                await self._message_handler(message)
            if not self._closed:
                failure = CodexAppServerError(
                    f"Codex App Server exited unexpectedly with code {process.returncode}"
                )
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            failure = error
        finally:
            if failure is not None:
                self._fail_pending(failure)
                await self._message_handler(
                    {"method": "$process/exited", "params": {"error": str(failure)}}
                )

    async def _read_stderr(self) -> None:
        process = self._process
        assert process is not None and process.stderr is not None
        while line := await process.stderr.readline():
            self.stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())
            del self.stderr_tail[:-50]

    def _fail_pending(self, error: BaseException) -> None:
        pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(error)


class CodexAppServerDriver(AgentDriver):
    """Translate Codex thread/turn APIs into one isolated run per worker."""

    def __init__(
        self,
        *,
        command: Sequence[str] = ("codex", "app-server", "--stdio"),
        request_timeout_s: float = 30.0,
        ephemeral_threads: bool = False,
    ) -> None:
        self._descriptor = AgentCapabilityDescriptor(
            driver_kind="codex-app-server",
            driver_version="0.1.0",
            protocol_version="2",
            capabilities=frozenset(
                {
                    AgentCapability.STATUS_LOOKUP,
                    AgentCapability.RESUME,
                    AgentCapability.EVENT_STREAM,
                    AgentCapability.STEERING,
                    AgentCapability.CANCEL,
                    AgentCapability.WORKSPACE_ISOLATION,
                    AgentCapability.STRUCTURED_RESULT,
                    AgentCapability.USAGE_REPORTING,
                }
            ),
        )
        self._client = _JsonlRpcClient(
            command,
            message_handler=self._handle_message,
            request_timeout_s=request_timeout_s,
        )
        self._ephemeral_threads = ephemeral_threads
        self._runs_by_worker: dict[str, _CodexRun] = {}
        self._runs_by_dispatch: dict[str, _CodexRun] = {}
        self._runs_by_thread: dict[str, _CodexRun] = {}
        self._runs_by_turn: dict[tuple[str, str], _CodexRun] = {}
        self._registry_lock = asyncio.Lock()

    async def capabilities(self) -> AgentCapabilityDescriptor:
        return self._descriptor

    async def start(self, request: AgentStartRequest) -> AgentRunHandle:
        async with self._registry_lock:
            existing = self._runs_by_dispatch.get(request.dispatch_token)
            if existing is not None:
                if existing.handle.worker_id != request.worker_id:
                    raise ValueError("dispatch token already belongs to another worker")
                return existing.handle

            thread_result = await self._client.request(
                "thread/start",
                {
                    "cwd": request.workspace.root,
                    "model": request.model,
                    "approvalPolicy": "never",
                    "sandbox": _sandbox_mode(request.workspace.mode),
                    "runtimeWorkspaceRoots": list(
                        request.workspace.allowed_roots or (request.workspace.root,)
                    ),
                    "ephemeral": self._ephemeral_threads,
                },
            )
            thread_id = _required_id(thread_result, "thread", "id")
            provisional = AgentRunHandle(
                worker_id=request.worker_id,
                dispatch_token=request.dispatch_token,
                locator=AgentRunLocator(
                    driver_kind=self._descriptor.driver_kind,
                    backend_session_id=thread_id,
                ),
                capabilities=self._descriptor,
            )
            run = _CodexRun(handle=provisional)
            self._register(run)

            try:
                turn_result = await self._client.request(
                    "turn/start",
                    {
                        "threadId": thread_id,
                        "input": [{"type": "text", "text": request.instruction}],
                        "clientUserMessageId": request.dispatch_token,
                        "outputSchema": request.output_schema,
                    },
                )
            except BaseException:
                self._unregister(run)
                raise
            turn_id = _required_id(turn_result, "turn", "id")
            run.handle = replace(
                provisional,
                locator=replace(provisional.locator, backend_run_id=turn_id),
            )
            run.phase = AgentRunPhase.RUNNING
            self._runs_by_turn[(thread_id, turn_id)] = run

        await self._emit(run, AgentRunStarted)
        run.ready_for_events = True
        pending, run.pending_messages = run.pending_messages, []
        for message in pending:
            await self._handle_message(message)
        return run.handle

    async def resume(
        self,
        locator: AgentRunLocator,
        *,
        worker_id: str,
        dispatch_token: str,
        after_sequence: int,
    ) -> AgentRunHandle:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        async with self._registry_lock:
            existing = self._runs_by_worker.get(worker_id)
            if existing is not None:
                if (
                    existing.handle.locator != locator
                    or existing.handle.dispatch_token != dispatch_token
                ):
                    raise ValueError("resume identity does not match the existing Codex run")
                return existing.handle
            result = await self._client.request(
                "thread/resume",
                {"threadId": locator.backend_session_id, "excludeTurns": False},
            )
            thread = _mapping(result.get("thread"), "thread/resume.thread")
            turns = thread.get("turns", [])
            turn = _find_turn(turns, locator.backend_run_id)
            phase = _codex_phase(turn.get("status") if turn else None)
            handle = AgentRunHandle(
                worker_id=worker_id,
                dispatch_token=dispatch_token,
                locator=locator,
                capabilities=self._descriptor,
            )
            run = _CodexRun(
                handle=handle,
                phase=phase,
                sequence_offset=after_sequence,
            )
            if turn is not None:
                run.result = _result_from_turn(turn)
                error = turn.get("error")
                run.error = _error_text(error) if error else None
            self._register(run)
            if locator.backend_run_id:
                self._runs_by_turn[(locator.backend_session_id, locator.backend_run_id)] = run

        run.ready_for_events = True
        return handle

    async def status(self, handle: AgentRunHandle) -> AgentRunSnapshot:
        run = self._get(handle)
        result = await self._client.request(
            "thread/read",
            {"threadId": handle.locator.backend_session_id, "includeTurns": True},
        )
        thread = _mapping(result.get("thread"), "thread/read.thread")
        turn = _find_turn(thread.get("turns", []), handle.locator.backend_run_id)
        if turn is not None:
            run.phase = _codex_phase(turn.get("status"))
            run.result = _result_from_turn(turn) or run.result
            error = turn.get("error")
            run.error = _error_text(error) if error else run.error
        return AgentRunSnapshot(
            worker_id=handle.worker_id,
            phase=run.phase,
            locator=handle.locator,
            last_event_sequence=run.sequence_offset + len(run.events),
            result=run.result,
            error=run.error,
        )

    async def events(
        self, handle: AgentRunHandle, *, after: int | None = None
    ) -> AsyncIterator[AgentEvent]:
        run = self._get(handle)
        cursor = after or 0
        upper = run.sequence_offset + len(run.events)
        if cursor < run.sequence_offset or cursor > upper:
            raise ValueError("Agent event cursor is outside the retained event history")
        while True:
            async with run.condition:
                await run.condition.wait_for(
                    lambda cursor=cursor: (
                        run.sequence_offset + len(run.events) > cursor
                        or run.phase.terminal
                        or run.stream_error is not None
                    )
                )
                pending = tuple(run.events[cursor - run.sequence_offset :])
                stream_error = run.stream_error
            for event in pending:
                cursor = event.sequence
                yield event
                if isinstance(event, AgentRunTerminal):
                    return
            if stream_error is not None:
                raise stream_error
            if run.phase.terminal and cursor >= run.sequence_offset + len(run.events):
                return

    async def send_input(self, handle: AgentRunHandle, input: AgentInput) -> None:
        run = self._get(handle)
        turn_id = handle.locator.backend_run_id
        if run.phase.terminal or not turn_id:
            raise RuntimeError("cannot steer an Agent run without an active turn")
        await self._client.request(
            "turn/steer",
            {
                "threadId": handle.locator.backend_session_id,
                "expectedTurnId": turn_id,
                "input": [{"type": "text", "text": input.text}],
                "clientUserMessageId": input.client_input_id,
            },
        )

    async def cancel(self, handle: AgentRunHandle, reason: str) -> CancelResult:
        run = self._get(handle)
        if run.phase.terminal:
            return CancelResult(
                requested=False,
                stopped=run.phase is AgentRunPhase.CANCELLED,
                phase=run.phase,
            )
        turn_id = handle.locator.backend_run_id
        if not turn_id:
            return CancelResult(requested=False, stopped=False, phase=run.phase)
        run.phase = AgentRunPhase.CANCELLING
        await self._emit(
            run,
            AgentProgressUpdated,
            text=f"Cancellation requested: {reason}",
            progress_version=len(run.events) + 1,
        )
        await self._client.request(
            "turn/interrupt",
            {"threadId": handle.locator.backend_session_id, "turnId": turn_id},
        )
        return CancelResult(
            requested=True,
            stopped=run.phase is AgentRunPhase.CANCELLED,
            phase=run.phase,
        )

    async def close(self, handle: AgentRunHandle) -> None:
        run = self._get(handle)
        try:
            await self._client.request(
                "thread/unsubscribe", {"threadId": handle.locator.backend_session_id}
            )
        finally:
            async with self._registry_lock:
                self._unregister(run)
                no_runs_remain = not self._runs_by_worker
            if no_runs_remain:
                await self._client.close()

    async def _handle_message(self, message: JsonObject) -> None:
        method = message.get("method")
        params = message.get("params", {})
        if not isinstance(method, str) or not isinstance(params, dict):
            return
        if method == "$process/exited":
            error = CodexAppServerError(str(params.get("error", "process exited")))
            for run in tuple(self._runs_by_worker.values()):
                if not run.phase.terminal:
                    run.stream_error = error
                    await self._notify(run)
            return
        if "id" in message:
            await self._handle_server_request(message, method, params)
            return

        run = self._run_for_params(params)
        if run is None:
            return
        if not run.ready_for_events:
            run.pending_messages.append(message)
            return
        if method == "item/agentMessage/delta":
            delta = str(params.get("delta", ""))
            if delta:
                run.response_parts.append(delta)
                await self._emit(run, AgentMessageDelta, text=delta)
        elif method == "item/plan/delta":
            await self._emit(run, AgentPlanUpdated, text=str(params.get("delta", "")))
        elif method == "turn/plan/updated":
            plan = params.get("plan", [])
            await self._emit(
                run,
                AgentPlanUpdated,
                text=json.dumps(plan, ensure_ascii=False, separators=(",", ":")),
            )
        elif method == "thread/tokenUsage/updated":
            usage = params.get("tokenUsage", {})
            total = usage.get("total", {}) if isinstance(usage, dict) else {}
            await self._emit(
                run,
                AgentUsageUpdated,
                input_tokens=int(total.get("inputTokens", 0)),
                cached_input_tokens=int(total.get("cachedInputTokens", 0)),
                output_tokens=int(total.get("outputTokens", 0)),
            )
        elif method == "warning":
            await self._emit(
                run,
                AgentProgressUpdated,
                text=str(params.get("message", "Codex warning")),
                progress_version=len(run.events) + 1,
            )
        elif method == "error" and not bool(params.get("willRetry")):
            run.error = _error_text(params.get("error"))
        elif method == "turn/completed":
            await self._handle_turn_completed(run, params)

    async def _handle_server_request(
        self, message: JsonObject, method: str, params: JsonObject
    ) -> None:
        run = self._run_for_params(params)
        if run is not None:
            request_id = str(message["id"])
            if method in {
                "item/tool/requestUserInput",
                "mcpServer/elicitation/request",
            }:
                await self._emit(
                    run,
                    AgentInputRequested,
                    request_id=request_id,
                    prompt=_request_prompt(params),
                )
            else:
                await self._emit(
                    run,
                    AgentPermissionRequested,
                    request_id=request_id,
                    method=method,
                    payload=params,
                )
        await self._client.respond_error(
            message["id"],
            "OpenRealtime denies unbound Codex server requests; "
            "authorize through Tool Policy Gateway",
        )

    async def _handle_turn_completed(self, run: _CodexRun, params: JsonObject) -> None:
        turn = params.get("turn", {})
        if not isinstance(turn, dict):
            turn = {}
        phase = _codex_phase(turn.get("status"))
        if not phase.terminal:
            return
        result = _result_from_turn(turn) or "".join(run.response_parts) or None
        error = _error_text(turn.get("error")) if turn.get("error") else run.error
        if phase is AgentRunPhase.SUCCEEDED:
            error = None
        else:
            result = None
            error = error or f"Codex turn ended with status {turn.get('status')!r}"
        await self._emit_terminal(run, phase, result=result, error=error)

    async def _emit_terminal(
        self,
        run: _CodexRun,
        phase: AgentRunPhase,
        *,
        result: str | None,
        error: str | None,
    ) -> None:
        if run.phase.terminal and any(isinstance(event, AgentRunTerminal) for event in run.events):
            return
        run.phase = phase
        run.result = result
        run.error = error
        await self._emit(
            run,
            AgentRunTerminal,
            phase=phase,
            result=result,
            error=error,
        )

    async def _emit(
        self,
        run: _CodexRun,
        event_type: type[AgentEventBase],
        **values: object,
    ) -> None:
        async with run.condition:
            event = event_type(
                worker_id=run.handle.worker_id,
                event_id=str(uuid.uuid4()),
                sequence=run.sequence_offset + len(run.events) + 1,
                occurred_at=utc_now(),
                locator=run.handle.locator,
                **values,
            )
            run.events.append(event)
            run.condition.notify_all()

    async def _notify(self, run: _CodexRun) -> None:
        async with run.condition:
            run.condition.notify_all()

    def _register(self, run: _CodexRun) -> None:
        self._runs_by_worker[run.handle.worker_id] = run
        self._runs_by_dispatch[run.handle.dispatch_token] = run
        self._runs_by_thread[run.handle.locator.backend_session_id] = run

    def _unregister(self, run: _CodexRun) -> None:
        self._runs_by_worker.pop(run.handle.worker_id, None)
        self._runs_by_dispatch.pop(run.handle.dispatch_token, None)
        self._runs_by_thread.pop(run.handle.locator.backend_session_id, None)
        turn_id = run.handle.locator.backend_run_id
        if turn_id:
            self._runs_by_turn.pop((run.handle.locator.backend_session_id, turn_id), None)

    def _get(self, handle: AgentRunHandle) -> _CodexRun:
        run = self._runs_by_worker.get(handle.worker_id)
        if run is None or run.handle != handle:
            raise KeyError(handle.worker_id)
        return run

    def _run_for_params(self, params: Mapping[str, Any]) -> _CodexRun | None:
        thread_id = params.get("threadId")
        turn_id = params.get("turnId")
        if isinstance(thread_id, str) and isinstance(turn_id, str):
            run = self._runs_by_turn.get((thread_id, turn_id))
            if run is not None:
                return run
        if isinstance(thread_id, str):
            return self._runs_by_thread.get(thread_id)
        return None


def _sandbox_mode(mode: WorkspaceMode) -> str:
    return {
        WorkspaceMode.READ_ONLY: "read-only",
        WorkspaceMode.PRIVATE_WRITABLE: "workspace-write",
        WorkspaceMode.EXCLUSIVE_SHARED: "workspace-write",
    }[mode]


def _mapping(value: object, name: str) -> JsonObject:
    if not isinstance(value, dict):
        raise CodexAppServerError(f"Codex response field {name!r} must be an object")
    return value


def _required_id(result: Mapping[str, Any], object_key: str, id_key: str) -> str:
    value = _mapping(result.get(object_key), object_key).get(id_key)
    if not isinstance(value, str) or not value:
        raise CodexAppServerError(f"Codex response is missing {object_key}.{id_key}")
    return value


def _find_turn(turns: object, turn_id: str | None) -> JsonObject | None:
    if not isinstance(turns, list):
        return None
    if turn_id is None:
        return turns[-1] if turns and isinstance(turns[-1], dict) else None
    return next(
        (turn for turn in turns if isinstance(turn, dict) and turn.get("id") == turn_id),
        None,
    )


def _codex_phase(status: object) -> AgentRunPhase:
    return {
        "inProgress": AgentRunPhase.RUNNING,
        "completed": AgentRunPhase.SUCCEEDED,
        "failed": AgentRunPhase.FAILED,
        "interrupted": AgentRunPhase.CANCELLED,
    }.get(status, AgentRunPhase.UNKNOWN)


def _result_from_turn(turn: Mapping[str, Any]) -> str | None:
    items = turn.get("items", [])
    if not isinstance(items, list):
        return None
    messages = [
        item.get("text")
        for item in items
        if isinstance(item, dict)
        and item.get("type") == "agentMessage"
        and isinstance(item.get("text"), str)
    ]
    return messages[-1] if messages else None


def _error_text(error: object) -> str:
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    if isinstance(error, str):
        return error
    return json.dumps(error, ensure_ascii=False, default=str)


def _request_prompt(params: Mapping[str, Any]) -> str:
    for key in ("prompt", "message", "reason"):
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    return "Codex requested additional user input"
