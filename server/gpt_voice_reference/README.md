# Minimal GPT Voice-style coordinator

This package distills the locally observed Codex Voice orchestration into one
small public interface:

```python
events = await agent.submit_turn(text)
events = await agent.complete_worker(worker_id, result=text)
events = await agent.fail_worker(worker_id, error=message)
events = await agent.cancel_worker(worker_id)
events = await agent.interrupt_output()
agent.mark_output_finished()
state = agent.snapshot()
```

The module hides a control loop behind that interface. A `RealtimeSession`
chooses one of five actions:

- `Speak`: answer immediately.
- `CallTool`: synchronously await a quick tool and ask Realtime to continue.
- `DelegateTask`: start a non-blocking worker and acknowledge immediately.
- `RequireConfirmation`: stop before a sensitive side effect.
- `EndSession`: close the voice session explicitly.

There are three replaceable seams:

- `RealtimeSession`: adapt an OpenAI Realtime WebRTC/DataChannel plus server
  sideband session into `next_action()` and `cancel_output()`.
- `ToolExecutor`: normalize function calling, MCP, skills, or app connectors
  behind one execution interface.
- `WorkerManager`: adapt Codex threads, a queue, Temporal, Celery, or another
  durable task runtime.

`InMemoryRealtimeSession`, `InMemoryToolExecutor`, and
`InMemoryWorkerManager` are deterministic adapters for tests and the demo;
they are not production network implementations.

Run the reference behavior:

```bash
.venv/bin/python -m pytest tests/gpt_voice_reference/test_voice_agent.py -q
PYTHONPATH=. .venv/bin/python demos/gpt_voice_reference_demo.py
```

The browser worklet in
`examples/gpt_voice_reference/realtime-prebuffer-worklet.js` is a clean-room
implementation of the observed 30-second startup buffer, 0.003 silence
threshold, and 100ms pre-roll behavior. Send `{type: "release"}` after all
Realtime startup barriers are satisfied.
