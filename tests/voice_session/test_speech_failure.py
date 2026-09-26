from server.voice_session.speech_failure import provider_failure_frame


def test_personal_quota_is_identified_without_exposing_vendor_message():
    frame = provider_failure_frame("tts", "personal", "Insufficient balance for secret-key-123")
    assert frame.code == "personal_quota_exhausted"
    assert "你的语音合成额度不足" in frame.safe_message
    assert "secret-key-123" not in frame.safe_message
    assert frame.session_disposition == "close"


def test_rate_limit_is_not_misreported_as_exhausted_quota():
    frame = provider_failure_frame("asr", "platform", "HTTP 429 Too Many Requests")
    assert frame.code == "provider_rate_limited"
    assert "额度不足" not in frame.safe_message


def test_unknown_speech_failure_is_safe_provider_outage():
    frame = provider_failure_frame("asr", "platform", "socket broke; token=secret")
    assert frame.code == "speech_provider_unavailable"
    assert "secret" not in frame.safe_message


def test_llm_quota_names_the_personal_source_without_fallback():
    frame = provider_failure_frame("brain", "personal", "quota exceeded")
    assert frame.code == "personal_quota_exhausted"
    assert "你的对话模型额度不足" in frame.safe_message
