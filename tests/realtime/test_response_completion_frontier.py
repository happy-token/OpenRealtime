"""A last model delta is not a durable context permission through completion."""

import asyncio

import pytest

from server.realtime import AudioDelta, ResponseCompleted, ResponseFailed
from server.realtime.capabilities.brain_streaming import BrainDelegationCall
from server.realtime.speech.delivery import InMemorySpeechDeliveryStore
from tests.realtime.test_brain_heard_frontier import terminal
from tests.realtime.test_reply_playback_observation import Provider, playing_core
from tests.realtime.test_response_context_frontier import next_input, position


@pytest.mark.parametrize("stage", ["model_completion", "tts_completion", "response_settlement", "delegation_settlement"])
@pytest.mark.parametrize("heard_text_changes", [True, False])
async def test_late_prior_playback_after_last_text_invalidates_response_completion(monkeypatch, stage, heard_text_changes):
    entered, release = asyncio.Event(), asyncio.Event()

    class Brain:
        def __init__(self):
            self.calls = 0

        async def stream(self, turn):
            self.calls += 1
            if self.calls == 1:
                yield "第一句。第二句。"
                return
            if stage == "delegation_settlement":
                yield BrainDelegationCall(delegation_request_id="work", instruction="inspect")
                return
            yield "依据之前内容的响应。"
            if stage == "model_completion":
                entered.set()
                await release.wait()

    class Tts:
        def __init__(self):
            self.calls = 0
            self.closed = False

        async def synthesize_duplex(self, texts):
            self.calls += 1
            try:
                text = "".join([value async for value in texts])
                if self.calls == 2 and stage == "response_settlement":
                    return
                if self.calls == 2 and stage == "tts_completion":
                    entered.set()
                    await release.wait()
                async for chunk in Provider().synthesize_stream(text):
                    yield chunk
            finally:
                if self.calls == 2:
                    self.closed = True

    brain, tts = Brain(), Tts()
    core, bridge = await playing_core(brain=brain, managed=True, tts=tts,
        speech_deliveries=InMemorySpeechDeliveryStore())
    conversation = bridge._conversation
    settle = core._settle_input_response

    async def gated_settlement(response_id, **kwargs):
        if response_id == "next-response" and stage.endswith("settlement"):
            entered.set()
            await release.wait()
        return await settle(response_id, **kwargs)

    monkeypatch.setattr(core, "_settle_input_response", gated_settlement)
    try:
        await position(bridge, 500)
        await conversation.send(await next_input(core, conversation))
        await asyncio.wait_for(entered.wait(), 1)
        await position(bridge, 2000 if heard_text_changes else 700)
        release.set()
        received = await terminal(conversation)
        if heard_text_changes:
            assert isinstance(received[-1], ResponseFailed)
            assert "new reply version" in received[-1].error
            assert not any(isinstance(event, (AudioDelta, ResponseCompleted)) for event in received)
        else:
            assert isinstance(received[-1], ResponseCompleted)
            assert not any(isinstance(event, ResponseFailed) for event in received)
        assert brain.calls == 2
        assert tts.closed is (stage != "delegation_settlement")
    finally:
        release.set()
        await conversation.close()


@pytest.mark.parametrize("burst", [1, 128])
@pytest.mark.parametrize("model_finishes", [False, True])
async def test_tts_detected_frontier_failure_finishes_owner_and_drains_full_queue(burst, model_finishes):
    from server.realtime import RealtimeCapabilityFailed
    from server.speech.tts import SynthesizedAudioChunk

    entered, release, model_closed, tts_closed = (asyncio.Event() for _ in range(4))

    class Brain:
        def __init__(self):
            self.calls = 0

        async def stream(self, turn):
            self.calls += 1
            if self.calls == 1:
                yield "第一句。第二句。"
                return
            try:
                yield "依据旧历史的回复。"
                if not model_finishes:
                    await asyncio.Event().wait()
            finally:
                model_closed.set()

    class Tts:
        def __init__(self):
            self.calls = 0

        async def synthesize_duplex(self, texts):
            self.calls += 1
            try:
                async for value in texts:
                    if self.calls == 1:
                        async for chunk in Provider().synthesize_stream(value):
                            yield chunk
                    else:
                        entered.set()
                        await release.wait()
                        for _ in range(burst):
                            yield SynthesizedAudioChunk(pcm16=b"\x00\x00", sample_rate_hz=1000, is_final=False)
            finally:
                if self.calls == 2:
                    tts_closed.set()

    brain = Brain()
    core, bridge = await playing_core(brain=brain, managed=True, tts=Tts(),
        speech_deliveries=InMemorySpeechDeliveryStore())
    core._response_timeout_s = 2
    core._response_cancel_timeout_s = .1
    conversation = bridge._conversation
    try:
        await conversation.send(await next_input(core, conversation))
        await asyncio.wait_for(entered.wait(), 1)
        await position(bridge, 2000)
        began = asyncio.get_running_loop().time()
        release.set()
        async with asyncio.timeout(.5):
            received = await terminal(conversation)
        assert isinstance(received[-1], ResponseFailed)
        assert "during TTS delivery" in received[-1].error
        assert "deadline exceeded" not in received[-1].error
        assert "TTS cleanup failed" not in received[-1].error
        assert asyncio.get_running_loop().time() - began < .5
        assert not any(isinstance(event, (AudioDelta, ResponseCompleted)) for event in received)
        assert not any(isinstance(event, RealtimeCapabilityFailed) and event.capability == "tts" for event in received)
        assert model_closed.is_set() and tts_closed.is_set()
        assert not core._brain._requests and not core._tts_task_by_response_id
        assert not core._detached_response_tasks and not core._tts_cleanup_unconfirmed
    finally:
        release.set()
        await conversation.close()


async def test_already_failed_tts_preserves_supplier_error_without_false_cleanup_failure():
    class Brain:
        def __init__(self):
            self.calls = 0

        async def stream(self, turn):
            self.calls += 1
            yield "第一句。第二句。" if self.calls == 1 else "有效响应。"

    class Tts:
        def __init__(self):
            self.calls = 0

        async def synthesize_duplex(self, texts):
            self.calls += 1
            text = "".join([value async for value in texts])
            if self.calls == 2:
                raise RuntimeError("ordinary TTS provider error")
            async for chunk in Provider().synthesize_stream(text):
                yield chunk

    core, bridge = await playing_core(brain=Brain(), managed=True, tts=Tts(),
        speech_deliveries=InMemorySpeechDeliveryStore())
    conversation = bridge._conversation
    try:
        await conversation.send(await next_input(core, conversation))
        received = await terminal(conversation)
        assert isinstance(received[-1], ResponseFailed)
        assert received[-1].error == "ordinary TTS provider error"
        assert not core._tts_task_by_response_id and not core._tts_cleanup_unconfirmed
    finally:
        await conversation.close()


@pytest.mark.parametrize("provider_budget,owner_budget", [(.02, .08), (.4, .025)])
async def test_unconfirmed_tts_cleanup_preserves_failure_and_rejects_new_requests(provider_budget, owner_budget):
    from dataclasses import replace

    from server.speech.tts import SynthesizedAudioChunk
    from tests.realtime.test_input_association_production import wait_for

    entered, release_audio, release_cleanup, cleanup_entered, cleaned = (asyncio.Event() for _ in range(5))

    class Brain:
        def __init__(self):
            self.calls = 0

        async def stream(self, turn):
            self.calls += 1
            yield "第一句。第二句。" if self.calls == 1 else "依据旧历史的回复。"
            if self.calls == 2:
                await asyncio.Event().wait()

    class Tts:
        def __init__(self):
            self.calls = 0

        async def synthesize_duplex(self, texts):
            self.calls += 1
            try:
                async for value in texts:
                    if self.calls == 1:
                        async for chunk in Provider().synthesize_stream(value):
                            yield chunk
                    else:
                        entered.set()
                        await release_audio.wait()
                        yield SynthesizedAudioChunk(pcm16=b"\x00\x00", sample_rate_hz=1000, is_final=False)
            finally:
                if self.calls == 2:
                    cleanup_entered.set()
                    while not release_cleanup.is_set():
                        try:
                            await release_cleanup.wait()
                        except asyncio.CancelledError:
                            continue
                    cleaned.set()

    brain = Brain()
    core, bridge = await playing_core(brain=brain, managed=True, tts=Tts(),
        speech_deliveries=InMemorySpeechDeliveryStore())
    core._response_timeout_s = 2
    core._response_cancel_timeout_s = owner_budget
    core._tts._cancel_timeout_s = provider_budget
    conversation = bridge._conversation
    try:
        command = await next_input(core, conversation)
        await conversation.send(command)
        await asyncio.wait_for(entered.wait(), 1)
        await position(bridge, 2000)
        release_audio.set()
        async with asyncio.timeout(.5):
            received = await terminal(conversation)
        assert isinstance(received[-1], ResponseFailed)
        assert "during TTS delivery" in received[-1].error
        assert "TTS cleanup failed" in received[-1].error
        assert cleanup_entered.is_set() and not cleaned.is_set()
        assert core._tts_cleanup_unconfirmed
        await wait_for(lambda: core._response_task is None)
        await conversation.send(replace(command, command_id="retry", idempotency_key="retry", response_id="retry"))
        retry = await terminal(conversation)
        assert isinstance(retry[-1], ResponseFailed)
        assert "requires a new capability session" in retry[-1].error
        assert brain.calls == 2
        from server.realtime import DeliverItem, DeliveryMode, StartSpeech

        with pytest.raises(RuntimeError, match="requires a new capability session"):
            await core.send(StartSpeech(command_id="external", idempotency_key="external", context=command.context, speech_id="external"))
        for mode in (DeliveryMode.SPEECH, DeliveryMode.MODEL_RESPONSE):
            with pytest.raises(RuntimeError, match="requires a new capability session"):
                await core.send(DeliverItem(command_id=mode.value, idempotency_key=mode.value,
                    context=command.context, item_id="next", delivery_id=mode.value, mode=mode))
        release_cleanup.set()
        await wait_for(lambda: cleaned.is_set() and not core._detached_response_tasks and not core._tts._detached_tasks)
    finally:
        release_audio.set()
        release_cleanup.set()
        await conversation.close()


async def test_cancelled_response_waiter_keeps_shared_tts_cleanup_and_admission_lock(monkeypatch):
    from server.realtime import CancelResponse, DeliverItem, DeliveryMode, StartSpeech
    from server.realtime.capabilities.tts import CancelTts
    from server.speech.tts import SynthesizedAudioChunk
    from tests.realtime.test_input_association_production import wait_for

    entered, release_audio, cancel_entered, release_cancel, cleaned = (asyncio.Event() for _ in range(5))

    class Brain:
        def __init__(self):
            self.calls = 0

        async def stream(self, turn):
            self.calls += 1
            yield "第一句。第二句。" if self.calls == 1 else "依据旧历史的回复。"
            if self.calls == 2:
                await asyncio.Event().wait()

    class Tts:
        def __init__(self):
            self.calls = 0

        async def synthesize_duplex(self, texts):
            self.calls += 1
            try:
                async for value in texts:
                    if self.calls == 1:
                        async for chunk in Provider().synthesize_stream(value):
                            yield chunk
                    else:
                        entered.set()
                        await release_audio.wait()
                        for _ in range(128):
                            yield SynthesizedAudioChunk(pcm16=b"\x00\x00", sample_rate_hz=1000, is_final=False)
            finally:
                if self.calls == 2:
                    cleaned.set()

    brain, tts = Brain(), Tts()
    core, bridge = await playing_core(brain=brain, managed=True, tts=tts,
        speech_deliveries=InMemorySpeechDeliveryStore())
    core._response_cancel_timeout_s = .5
    conversation = bridge._conversation
    send = core._tts.send

    async def gated_cancel(command):
        if isinstance(command, CancelTts):
            cancel_entered.set()
            await release_cancel.wait()
        await send(command)

    monkeypatch.setattr(core._tts, "send", gated_cancel)
    try:
        command = await next_input(core, conversation)
        await conversation.send(command)
        await asyncio.wait_for(entered.wait(), 1)
        await position(bridge, 2000)
        release_audio.set()
        await asyncio.wait_for(cancel_entered.wait(), .3)
        operation = core._tts_stop_tasks[command.response_id]
        await conversation.send(CancelResponse(command_id="cancel", idempotency_key="cancel",
            context=command.context, response_id=command.response_id, reason="user_cancel"))
        received = await terminal(conversation)
        assert isinstance(received[-1], ResponseFailed)
        assert "cleanup waiter was cancelled" in received[-1].error
        assert not operation.done() and core._tts_cleanup_unconfirmed
        with pytest.raises(RuntimeError, match="requires a new capability session"):
            await core.send(StartSpeech(command_id="external", idempotency_key="external", context=command.context, speech_id="external"))
        for mode in (DeliveryMode.SPEECH, DeliveryMode.MODEL_RESPONSE):
            with pytest.raises(RuntimeError, match="requires a new capability session"):
                await core.send(DeliverItem(command_id=mode.value, idempotency_key=mode.value,
                    context=command.context, item_id="next", delivery_id=mode.value, mode=mode))
        assert brain.calls == tts.calls == 2
        release_cancel.set()
        await asyncio.wait_for(asyncio.shield(operation), .3)
        await wait_for(lambda: not core._detached_response_tasks)
        assert cleaned.is_set() and not core._tts_cleanup_unconfirmed
        assert not core._tts_stop_tasks and not core._tts_task_by_response_id
    finally:
        release_audio.set()
        release_cancel.set()
        await conversation.close()
