# Testing patterns

## Layout mirrors the package

`tests/` mirrors `server/`'s own structure — `tests/speech/`,
`tests/scheduler/`, `tests/bench/`, `tests/fixtures/` correspond to
`server/speech/`, `server/scheduler/`, etc. Most Seam-level tests sit
flat at `tests/test_<seam>.py` (e.g. `tests/test_turn_policy.py`,
`tests/test_router.py`, `tests/test_endpoint_session.py`); a subdirectory
appears once a Seam has enough plugin-specific tests to warrant one (e.g.
`tests/speech/` for ASR/TTS plugin tests).

Put a new test next to its Seam's existing tests, not in a new top-level
file, unless no matching file/directory exists yet.

## pytest-asyncio, no decorators

`pyproject.toml` sets `asyncio_mode = "auto"` — `async def test_...()`
functions run correctly with no `@pytest.mark.asyncio` decorator.

## Test doubles over mocks

This codebase favors small, explicit test-double classes over mocking
libraries — see `tests/test_turn_policy.py`'s `RejectingClassifier`,
`AllowingWakeWordDetector`: a plain class implementing the Seam's `Protocol`
with scripted behavior, given a docstring explaining what it fakes.

```python
class RejectingClassifier:
    """Test double: always says speech is not addressed to the assistant."""

    async def is_addressed(self, *, generation: int) -> bool:
        return False
```

For Seams with a real default implementation meant for testing
(`InMemory*`, `Preloaded*`), prefer that over writing a new double —
`InMemoryAgentSession` exposes `sent_content`/`cancelled`/`resolve()` etc.
specifically so tests don't need their own fakes.

## AAA structure, descriptive names

```python
async def test_tau1_idle_to_listen_on_user_onset():
    policy = TurnPolicy()

    transition = await policy.evaluate(Signal.USER_SPEECH_ONSET, generation=1)

    assert transition is not None
    assert transition.name == "τ1"
    assert policy.state is DialogueState.LISTEN
```

Name tests after the behavior, not the method under test — e.g.
`test_tau1_idle_to_listen_on_user_onset`, referencing the canonical
transition name from the Turn Policy FSM/full-duplex survey where relevant,
so a failure is legible without opening the test body.

## Live smoke tests: opt-in, not part of the default suite

`tests/live/` holds tests against real external vendors (e.g.
`test_bella_voice_pipeline_live.py` against the real Bella gateway). These:

- are skipped by default (a module-level `pytest.skip(...)` or an env-var
  guard),
- require an explicit opt-in env var to actually run, e.g.:

  ```
  RUN_LIVE=1 API_KEY=<real credential> uv run pytest tests/live
  ```

- exist to prove a real wire round-trip works end-to-end (e.g. synthesizing
  test audio via real TTS, streaming it through a real `ConversationKernel`
  over a real WebSocket, and asserting on the resulting frames) — not to run
  on every `pytest` invocation or in CI without credentials.

Do not add a new always-on test that depends on network access or a real
vendor credential; put it in `tests/live/` instead, following this
skip-by-default pattern.

## Running the suite

```sh
uv run pytest -q
uv run ruff check server servers tests
```
