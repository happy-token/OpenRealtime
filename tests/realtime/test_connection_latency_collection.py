from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock
import asyncio

from server.core.interaction_context import InteractionContext
from server.realtime.capabilities.asr import LegacyAsrCapabilityAdapter
from server.realtime.capabilities.tts import _warm_tts_engine
from server.turn_policy.plugins.jev_classifier import JEV_TIMING_OBSERVER, _timed_stage


class Telemetry:
    def __init__(self):
        self.calls = []

    @asynccontextmanager
    async def provider_call(self, **kwargs):
        self.calls.append(kwargs)
        yield

    def record(self, *args, **kwargs):
        pass


async def test_asr_connection_is_measured_before_session_delivery():
    telemetry = Telemetry()
    engine = Mock(start_session=AsyncMock(return_value=Mock()))
    context = InteractionContext('t', 'u', 'd', 's', 'thread', 'turn', 1)
    session = await LegacyAsrCapabilityAdapter(engine, telemetry=telemetry).open(context=context)
    assert session._session is engine.start_session.return_value
    assert telemetry.calls == [dict(provider='asr', operation='connection_setup', generation=1)]


async def test_tts_warmup_is_measured_and_runs_once():
    telemetry = Telemetry()
    warmup = AsyncMock()
    await _warm_tts_engine(warmup, telemetry)
    warmup.assert_awaited_once()
    assert telemetry.calls[0]['operation'] == 'connection_setup'
    assert telemetry.calls[0]['attributes'] == {'mode': 'preconnect'}


async def test_jev_stage_observer_is_scoped_to_each_task():
    async def run(label):
        rows = []
        token = JEV_TIMING_OBSERVER.set(lambda *args: rows.append((label, *args)))
        try:
            with _timed_stage('request'):
                await asyncio.sleep(0)
        finally:
            JEV_TIMING_OBSERVER.reset(token)
        return rows
    first, second = await asyncio.gather(run('one'), run('two'))
    assert len(first) == len(second) == 1
    assert first[0][0] == 'one' and second[0][0] == 'two'
    assert first[0][-1] == second[0][-1] == 'ok'
