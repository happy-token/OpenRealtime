"""Real provider timing -> capability -> wire/confirmed-heard boundaries."""

import asyncio
from dataclasses import replace

from server.realtime.capabilities.tts import (
    AppendTtsText,
    CommitTts,
    LegacyTtsCapabilityAdapter,
    StartTts,
    TtsAudioFrame,
    TtsCompleted,
    TtsTextAlignment,
)
from server.speech.plugins.doubao_tts_direct import _alignment_chunks
from server.speech.tts import SynthesizedAudioChunk
from tests.realtime.test_realtime_websocket_bridge import context


async def alignments_for(sentences, *, duplicate_pcm=False):
    class Provider:
        async def synthesize_stream(self, text):
            for sentence, start in sentences:
                chunks = list(
                    _alignment_chunks(
                        {
                            "text": sentence,
                            "words": [
                                {"word": sentence[:2], "startTime": start, "endTime": start + 0.5},
                                {
                                    "word": sentence[2:],
                                    "startTime": start + 0.5,
                                    "endTime": start + 1,
                                },
                            ],
                        },
                        1000,
                    )
                )
                for chunk in chunks:
                    yield chunk
                if duplicate_pcm:
                    yield replace(chunks[-1], pcm16=b"\x00\x00" * 20)

    session = await LegacyTtsCapabilityAdapter(Provider()).open(context=context())
    try:
        await session.send(StartTts(speech_id="speech"))
        await session.send(
            AppendTtsText(
                speech_id="speech",
                text_sequence=1,
                delta="".join(sentence for sentence, _ in sentences),
            )
        )
        await session.send(CommitTts(speech_id="speech"))
        result = []
        async with asyncio.timeout(0.5):
            async for event in session.events():
                result.append(event)
                if isinstance(event, TtsCompleted):
                    break
        return result
    finally:
        await session.close()


async def test_global_second_sentence_time_advances_only_its_local_fraction():
    events = await alignments_for([("第一句。", 0), ("第二句。", 2)])
    cues = [event for event in events if isinstance(event, TtsTextAlignment)]
    assert [cue.text_end for cue in cues] == [2, 4, 6, 8]


async def test_repeated_sentence_has_distinct_stable_identity_and_exact_text_offsets():
    events = await alignments_for([("第一句。", 0), ("第一句。", 2)])
    cues = [event for event in events if isinstance(event, TtsTextAlignment)]
    assert [cue.text_end for cue in cues] == [2, 4, 6, 8]
    spans = [getattr(cue, "sentence", None) for cue in cues]
    assert all(span is not None for span in spans)
    assert spans[0] == spans[1] and spans[2] == spans[3]
    assert spans[0].sentence_id != spans[2].sentence_id
    assert [
        (span.text_start, span.text_end, span.audio_start_us, span.audio_end_us)
        for span in (spans[0], spans[2])
    ] == [(0, 4, 0, 1_000_000), (4, 8, 2_000_000, 3_000_000)]


async def test_duplicate_alignment_must_not_drop_real_pcm_payload():
    events = await alignments_for([("第一句。", 0)], duplicate_pcm=True)
    assert [len(event.frame.data) for event in events if isinstance(event, TtsAudioFrame)] == [40]


async def test_fractional_caption_is_not_claimed_as_exact_heard_text():
    events = await alignments_for([("第一句。", 0)])
    cues = [event for event in events if isinstance(event, TtsTextAlignment)]
    assert [getattr(cue, "text_end_precision", None) for cue in cues] == ["estimated", "exact"]


async def test_actual_bridge_heard_frontier_ignores_estimated_caption_and_tracks_complete_sentences():
    from datetime import UTC, datetime

    from server.realtime import AudioEncoding, AudioFrame
    from server.realtime.protocol.events import (
        SpeechAudioDelta,
        SpeechStarted,
        SpeechTextAccepted,
        SpeechTextAlignment,
    )
    from server.realtime.transport import RealtimeWebSocketFrameBridge
    from server.voice_session.protocol import PlaybackProgressV2
    from tests.realtime.test_realtime_websocket_bridge import (
        RecordingConversation,
        RecordingTransport,
    )

    conversation, transport = RecordingConversation(), RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(), conversation=conversation, transport=transport, output_epoch="epoch"
    )
    fields = {"context": context(), "occurred_at": datetime.now(UTC), "speech_id": "speech"}
    from server.realtime import InterruptedContextPolicy, SpeechContextPolicy

    await bridge.handle_event(
        SpeechStarted(
            event_id="start",
            conversation_sequence=1,
            source_item_id=None,
            context_policy=SpeechContextPolicy.AUTO,
            interrupted_context_policy=InterruptedContextPolicy.DELIVERED_ONLY,
            **fields,
        )
    )
    await bridge.handle_event(
        SpeechTextAccepted(
            event_id="text",
            conversation_sequence=2,
            text_sequence=1,
            delta="第一句。第二句。",
            **fields,
        )
    )
    await bridge.handle_event(
        SpeechAudioDelta(
            event_id="audio",
            conversation_sequence=3,
            segment_index=0,
            frame=AudioFrame(
                stream_id="tts",
                sequence=0,
                timestamp_us=0,
                duration_us=3_000_000,
                encoding=AudioEncoding.PCM_S16LE,
                sample_rate_hz=1000,
                channels=1,
                data=b"\x00\x00" * 3000,
            ),
            **fields,
        )
    )
    events = await alignments_for([("第一句。", 0), ("第二句。", 2)])
    for index, cue in enumerate(e for e in events if isinstance(e, TtsTextAlignment)):
        await bridge.handle_event(
            SpeechTextAlignment(
                event_id=f"cue-{index}",
                conversation_sequence=4 + index,
                text_end=cue.text_end,
                audio_start_us=cue.audio_start_us,
                audio_end_us=cue.audio_end_us,
                text_end_precision=cue.text_end_precision,
                sentence=cue.sentence,
                **fields,
            )
        )
    for position, expected in [(500, 0), (1000, 4), (2500, 4), (3000, 8)]:
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch="epoch",
                speech_id="speech",
                generation=1,
                phase="playing",
                played_position_samples=position,
            )
        )
        assert conversation.commands[-1].delivered_text_end == expected


def test_sentence_wire_rejects_coercion_and_requires_complete_target():
    import pytest
    from pydantic import ValidationError

    from server.transport.frames import AssistantTextAlignmentFrame

    sentence = {
        "sentence_id": "sentence",
        "text": "好😀。",
        "text_start": 0,
        "text_end": 3,
        "audio_start_us": 0,
        "audio_end_us": 100_000,
    }
    frame = {
        "generation": 1,
        "speech_id": "speech",
        "output_epoch": "epoch",
        "text": "好😀。",
        "audio_start_us": 0,
        "audio_end_us": 100_000,
        "sentence": sentence,
    }
    assert AssistantTextAlignmentFrame(**frame).model_dump()["sentence"] == sentence
    for value in (True, "0", 0.5):
        with pytest.raises((ValidationError, ValueError)):
            AssistantTextAlignmentFrame(**{**frame, "sentence": {**sentence, "text_start": value}})
        with pytest.raises((ValidationError, ValueError)):
            AssistantTextAlignmentFrame(**{**frame, "audio_start_us": value})
    with pytest.raises(ValidationError):
        AssistantTextAlignmentFrame(**{**frame, "output_epoch": None})


async def test_production_external_speech_forwards_provider_sentence_evidence_to_wire():
    from server.realtime import AppendSpeechText, CommitSpeech, StartSpeech
    from server.realtime.protocol.events import SpeechAudioCompleted
    from server.realtime.transport import RealtimeWebSocketFrameBridge
    from server.transport.frames import AssistantSpeechTextFrame, AssistantTextAlignmentFrame
    from tests.realtime.test_realtime_websocket_bridge import RecordingTransport
    from tests.realtime.test_reply_revision_production_delivery import open_core

    class AlignedProvider:
        async def synthesize_stream(self, text):
            yield SynthesizedAudioChunk(
                pcm16=b"\x00\x00" * 1000, sample_rate_hz=1000, is_final=False
            )
            for chunk in _alignment_chunks(
                {
                    "text": text,
                    "words": [
                        {"word": "好", "startTime": 0, "endTime": 0.5},
                        {"word": "😀", "startTime": 0.5, "endTime": 1},
                    ],
                },
                1000,
            ):
                yield chunk

    core = await open_core(tts=AlignedProvider(), interaction_context=context())
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(), conversation=core, transport=transport, output_epoch="epoch"
    )
    try:
        await core.send(
            StartSpeech(
                command_id="start", idempotency_key="start", context=context(), speech_id="speech"
            )
        )
        await core.send(
            AppendSpeechText(
                command_id="text",
                idempotency_key="text",
                context=context(),
                speech_id="speech",
                text_sequence=1,
                delta="好😀。",
            )
        )
        await core.send(
            CommitSpeech(
                command_id="commit", idempotency_key="commit", context=context(), speech_id="speech"
            )
        )
        async with asyncio.timeout(1):
            async for event in core.events():
                await bridge.handle_event(event)
                if isinstance(event, SpeechAudioCompleted):
                    break
        cues = [f for f in transport.frames if isinstance(f, AssistantTextAlignmentFrame)]
        assert len(cues) == 2
        assert [f.text for f in cues] == ["好😀", "好😀。"]
        assert [f.text_end_precision for f in cues] == ["estimated", "exact"]
        assert all(f.output_epoch == "epoch" and f.sentence.text == "好😀。" for f in cues)
        assert any(
            isinstance(f, AssistantSpeechTextFrame) and f.text == "好😀。" for f in transport.frames
        )
    finally:
        await core.close()


async def test_invalid_tail_word_cannot_mark_the_unplayed_whole_sentence_exact():
    class Provider:
        async def synthesize_stream(self, text):
            for chunk in _alignment_chunks(
                {
                    "text": text,
                    "words": [
                        {"word": "第一", "startTime": 0, "endTime": 0.1},
                        {"word": "句还没说完", "startTime": 0.1, "endTime": "invalid"},
                    ],
                },
                1000,
            ):
                yield chunk

    session = await LegacyTtsCapabilityAdapter(Provider()).open(context=context())
    try:
        await session.send(StartTts(speech_id="speech"))
        await session.send(
            AppendTtsText(speech_id="speech", text_sequence=1, delta="第一句还没说完。")
        )
        await session.send(CommitTts(speech_id="speech"))
        async with asyncio.timeout(0.5):
            async for event in session.events():
                if isinstance(event, TtsTextAlignment):
                    assert event.text_end_precision == "estimated"
                    assert event.sentence is None
                if isinstance(event, TtsCompleted):
                    break
    finally:
        await session.close()


async def test_sentence_optional_word_start_uses_sentence_origin_on_wire():
    from datetime import UTC, datetime

    from server.realtime import SpokenContentDelta
    from server.realtime.protocol.events import SpeechTextAlignment
    from server.realtime.protocol.playback import SentenceSpan, sentence_identity
    from server.realtime.transport import RealtimeWebSocketFrameBridge
    from server.transport.frames import AssistantTextAlignmentFrame
    from tests.realtime.test_realtime_websocket_bridge import (
        RecordingConversation,
        RecordingTransport,
        event_context,
    )

    ctx = event_context()
    transport = RecordingTransport()
    bridge = RealtimeWebSocketFrameBridge(
        context=context(),
        conversation=RecordingConversation(),
        transport=transport,
        output_epoch="epoch",
    )
    await bridge.handle_event(
        SpokenContentDelta(
            event_id="text",
            context=ctx,
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            response_id="response-1",
            response_sequence=1,
            delta="第一句。",
        )
    )
    span = SentenceSpan(
        sentence_id=sentence_identity(ctx, "response:response-1", "第一句。", 0),
        text="第一句。",
        text_start=0,
        text_end=4,
        audio_start_us=100_000,
        audio_end_us=200_000,
    )
    await bridge.handle_event(
        SpeechTextAlignment(
            event_id="cue",
            context=ctx,
            conversation_sequence=2,
            occurred_at=datetime.now(UTC),
            speech_id="response:response-1",
            audio_end_us=150_000,
            text_end=2,
            text_end_precision="estimated",
            sentence=span,
        )
    )
    frame = transport.frames[-1]
    assert isinstance(frame, AssistantTextAlignmentFrame)
    assert frame.audio_start_us == 100_000


def test_complete_sentence_extends_a_trusted_word_frontier_without_skipping_gaps():
    from server.realtime.protocol.playback import SentenceSpan
    from server.realtime.transport.websocket import RealtimeWebSocketFrameBridge, _PlaybackState

    state = _PlaybackState(generation=1, speech_id="speech", context=context())
    state.text_boundaries = [(500_000, 2)]
    state.sentences = {
        "sentence": SentenceSpan(
            sentence_id="sentence",
            text="第一句。",
            text_start=0,
            text_end=4,
            audio_start_us=0,
            audio_end_us=1_000_000,
        )
    }
    assert RealtimeWebSocketFrameBridge._confirmed_text_end(state, 500_000) == 2
    assert RealtimeWebSocketFrameBridge._confirmed_text_end(state, 1_000_000) == 4
    state.sentences = {
        "tail": SentenceSpan(
            sentence_id="tail",
            text="第二句。",
            text_start=4,
            text_end=8,
            audio_start_us=1_000_000,
            audio_end_us=2_000_000,
        )
    }
    assert RealtimeWebSocketFrameBridge._confirmed_text_end(state, 2_000_000) == 2


async def test_late_complete_timing_upgrades_estimated_caption_without_losing_sentence_anchor():
    class Provider:
        async def synthesize_stream(self, text):
            for words in (
                [
                    {"word": "第一", "startTime": 0, "endTime": 0.1},
                    {"word": "句还没说完", "startTime": 0.1, "endTime": "invalid"},
                ],
                [
                    {"word": "第一", "startTime": 0, "endTime": 0.1},
                    {"word": "句还没说完", "startTime": 0.1, "endTime": 1},
                ],
            ):
                for chunk in _alignment_chunks({"text": text, "words": words}, 1000):
                    yield chunk

    session = await LegacyTtsCapabilityAdapter(Provider()).open(context=context())
    cues = []
    try:
        await session.send(StartTts(speech_id="speech"))
        await session.send(
            AppendTtsText(speech_id="speech", text_sequence=1, delta="第一句还没说完。")
        )
        await session.send(CommitTts(speech_id="speech"))
        async with asyncio.timeout(0.5):
            async for event in session.events():
                if isinstance(event, TtsTextAlignment):
                    cues.append(event)
                if isinstance(event, TtsCompleted):
                    break
        assert [cue.text_end_precision for cue in cues] == ["estimated", "exact"]
        assert cues[-1].sentence.audio_end_us == 1_000_000
        assert cues[-1].sentence.text_start == 0
    finally:
        await session.close()


async def test_duplicate_word_tuple_can_upgrade_new_complete_sentence_evidence():
    class Provider:
        async def synthesize_stream(self, text):
            for words in (
                [
                    {"word": "你好", "startTime": 0, "endTime": 0.5},
                    {"word": "。", "startTime": 0.5, "endTime": "invalid"},
                ],
                [{"word": "你好", "startTime": 0, "endTime": 0.5}],
            ):
                for chunk in _alignment_chunks({"text": text, "words": words}, 1000):
                    yield chunk

    session = await LegacyTtsCapabilityAdapter(Provider()).open(context=context())
    cues = []
    try:
        await session.send(StartTts(speech_id="speech"))
        await session.send(AppendTtsText(speech_id="speech", text_sequence=1, delta="你好。"))
        await session.send(CommitTts(speech_id="speech"))
        async with asyncio.timeout(0.5):
            async for event in session.events():
                if isinstance(event, TtsTextAlignment):
                    cues.append(event)
                if isinstance(event, TtsCompleted):
                    break
        assert [cue.text_end_precision for cue in cues] == ["estimated", "exact"]
        assert cues[-1].sentence.audio_end_us == 500_000
    finally:
        await session.close()
