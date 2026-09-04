"""Tests for ByteWebSearch — the real, network-calling WebSearch conformer.
No real network: urllib.request.urlopen is monkeypatched, mirroring
tests/test_llm_clients.py's test-double pattern for the other real
HTTP-calling conformer.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
from typing import Self

import pytest

from server.observability.telemetry import (
    InMemoryTelemetryStore,
    RuntimeTelemetry,
    TelemetryIdentity,
    TelemetryKind,
    TelemetryOutcome,
)
from server.web_search.plugins import byte_web_search
from server.web_search.plugins.byte_web_search import (
    DEFAULT_BASE_URL,
    ByteWebSearch,
    ByteWebSearchError,
)
from server.web_search.protocol import LookupFailure


class FakeHttpResponse:
    """Supports chunked reads (an optional `size` argument), since the real
    client reads the body in bounded chunks rather than one `.read()` call."""

    def __init__(self, payload: dict | None = None, *, raw_body: bytes | None = None) -> None:
        self._body = raw_body if raw_body is not None else json.dumps(payload).encode("utf-8")
        self._offset = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self, size: int | None = None) -> bytes:
        if size is None:
            size = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def _web_results_payload(items: list[dict]) -> dict:
    return {"Result": {"WebResults": items}}


def test_constructor_uses_explicit_api_key_over_env_var(monkeypatch):
    monkeypatch.setenv("BYTE_WEB_SEARCH_API_KEY", "env-key")

    client = ByteWebSearch(api_key="explicit-key")

    assert client._api_key == "explicit-key"


def test_constructor_falls_back_to_env_var_api_key(monkeypatch):
    monkeypatch.setenv("BYTE_WEB_SEARCH_API_KEY", "env-key")

    client = ByteWebSearch()

    assert client._api_key == "env-key"


def test_search_api_key_prefers_canonical_name_over_legacy_name():
    key = byte_web_search.resolve_search_api_key(
        {
            "BYTE_WEB_SEARCH_API_KEY": "canonical-key",
            "WEB_SEARCH_API_KEY": "legacy-key",
        }
    )

    assert key == "canonical-key"


def test_search_api_key_accepts_legacy_name_with_deprecation_warning(caplog):
    key = byte_web_search.resolve_search_api_key({"WEB_SEARCH_API_KEY": "legacy-key"})

    assert key == "legacy-key"
    assert "WEB_SEARCH_API_KEY is deprecated" in caplog.text
    assert "legacy-key" not in caplog.text


async def test_missing_api_key_fails_before_any_network_request(monkeypatch):
    monkeypatch.delenv("BYTE_WEB_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("WEB_SEARCH_API_KEY", raising=False)
    called = False

    def fake_urlopen(request, timeout):
        nonlocal called
        called = True

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch()

    with pytest.raises(LookupFailure) as error:
        await client.search("query")

    assert error.value.reason == "provider_unavailable"
    assert called is False


def test_constructor_defaults_base_url(monkeypatch):
    monkeypatch.setenv("BYTE_WEB_SEARCH_API_KEY", "env-key")
    monkeypatch.delenv("BYTE_WEB_SEARCH_BASE_URL", raising=False)

    client = ByteWebSearch()

    assert client._base_url == DEFAULT_BASE_URL


def test_constructor_explicit_base_url_wins_over_env_var(monkeypatch):
    monkeypatch.setenv("BYTE_WEB_SEARCH_API_KEY", "env-key")
    monkeypatch.setenv("BYTE_WEB_SEARCH_BASE_URL", "https://env.example.com/search")

    client = ByteWebSearch(base_url="https://explicit.example.com/search")

    assert client._base_url == "https://explicit.example.com/search"


def test_constructor_env_var_base_url_wins_over_default(monkeypatch):
    monkeypatch.setenv("BYTE_WEB_SEARCH_API_KEY", "env-key")
    monkeypatch.setenv("BYTE_WEB_SEARCH_BASE_URL", "https://env.example.com/search")

    client = ByteWebSearch()

    assert client._base_url == "https://env.example.com/search"


async def test_search_posts_expected_request(monkeypatch):
    captured: dict = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeHttpResponse(_web_results_payload([]))

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret", base_url="https://example.com/search")

    with pytest.raises(LookupFailure, match="empty_result"):
        await client.search("today's weather", top_k=5)

    assert captured["url"] == "https://example.com/search"
    assert captured["method"] == "POST"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["headers"]["X-traffic-tag"] == "skill_web_search_common"
    assert captured["body"] == {
        "Query": "today's weather",
        "SearchType": "web",
        "Count": 5,
        "NeedSummary": True,
    }


async def test_search_uses_configured_timeout(monkeypatch):
    captured: dict = {}

    def fake_urlopen(request, timeout):
        captured["timeout"] = timeout
        return FakeHttpResponse(_web_results_payload([]))

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret", timeout_s=5.0)

    with pytest.raises(LookupFailure, match="empty_result"):
        await client.search("q")

    assert captured["timeout"] == 5.0


async def test_search_parses_well_formed_results_into_passages(monkeypatch):
    payload = _web_results_payload(
        [
            {
                "Title": "Result One",
                "Url": "https://example.com/1",
                "Summary": "Summary one",
                "SiteName": "Example",
            },
            {
                "Title": "Result Two",
                "Url": "https://news.example.org/2",
                "Snippet": "Snippet two",
            },
        ]
    )

    def fake_urlopen(request, timeout):
        return FakeHttpResponse(payload)

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret")

    evidence = await client.search("query")

    assert evidence.provider == "byte"
    assert evidence.query == "query"
    assert evidence.structured()["untrusted"] is True
    assert [(result.title, result.summary, result.source) for result in evidence.results] == [
        ("Result One", "Summary one", "example.com"),
        ("Result Two", "Snippet two", "news.example.org"),
    ]


async def test_search_recovers_from_a_transient_tls_eof(monkeypatch):
    attempts = 0
    payload = _web_results_payload(
        [
            {
                "Title": "北京天气",
                "Url": "https://weather.example.com/beijing",
                "Summary": "北京今天晴。",
            }
        ]
    )

    def flaky_urlopen(request, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise urllib.error.URLError(
                ssl.SSLEOFError(8, "EOF occurred in violation of protocol")
            )
        return FakeHttpResponse(payload)

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", flaky_urlopen)

    evidence = await ByteWebSearch(api_key="secret").search("北京天气")

    assert evidence.results[0].summary == "北京今天晴。"


async def test_search_records_provider_latency_without_storing_query(monkeypatch):
    payload = _web_results_payload(
        [{"Title": "Result", "Url": "https://example.com/1", "Summary": "Summary"}]
    )

    def fake_urlopen(request, timeout):
        return FakeHttpResponse(payload)

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    store = InMemoryTelemetryStore()
    runtime = RuntimeTelemetry(store)
    await runtime.start()
    telemetry = runtime.bind(
        TelemetryIdentity(
            tenant_id="tenant-1",
            user_id="user-1",
            device_id="device-1",
            voice_session_id="voice-1",
            thread_id="thread-1",
        )
    )
    client = ByteWebSearch(api_key="secret", telemetry=telemetry)

    await client.search("private query", top_k=2)
    await runtime.flush()
    detail = await store.session_detail("voice-1")

    assert detail is not None
    call = next(event for event in detail.events if event.kind is TelemetryKind.PROVIDER_CALL)
    assert call.name == "provider.byte.web_search"
    assert call.outcome is TelemetryOutcome.OK
    assert call.attributes["query_length"] == len("private query")
    assert "private query" not in str(call.to_dict())
    assert call.attributes["ttfb_ms"] is not None
    await runtime.close()


async def test_search_maps_typed_provider_timeout_to_timeout_metric(monkeypatch):
    def fake_urlopen(request, timeout):
        raise TimeoutError("upstream timed out")

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    store = InMemoryTelemetryStore()
    runtime = RuntimeTelemetry(store)
    await runtime.start()
    telemetry = runtime.bind(
        TelemetryIdentity(
            tenant_id="tenant-1",
            user_id="user-1",
            device_id="device-1",
            voice_session_id="voice-1",
            thread_id="thread-1",
        )
    )
    client = ByteWebSearch(api_key="secret", timeout_s=0.25, telemetry=telemetry)

    with pytest.raises(ByteWebSearchError):
        await client.search("query")
    await runtime.flush()
    detail = await store.session_detail("voice-1")

    assert detail is not None
    call = next(event for event in detail.events if event.kind is TelemetryKind.PROVIDER_CALL)
    assert call.outcome is TelemetryOutcome.TIMEOUT
    assert call.timeout_ms == 250
    await runtime.close()


async def test_search_skips_url_pointing_to_a_private_address(monkeypatch):
    payload = _web_results_payload(
        [
            {"Title": "Internal", "Url": "http://127.0.0.1/admin", "Summary": "s"},
            {"Title": "Public", "Url": "https://example.com/2", "Summary": "s"},
        ]
    )

    def fake_urlopen(request, timeout):
        return FakeHttpResponse(payload)

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret")

    evidence = await client.search("query")

    assert len(evidence.results) == 1
    assert evidence.results[0].title == "Public"


async def test_search_skips_url_with_embedded_credentials(monkeypatch):
    payload = _web_results_payload(
        [{"Title": "Sketchy", "Url": "https://user:pass@example.com/x", "Summary": "s"}]
    )

    def fake_urlopen(request, timeout):
        return FakeHttpResponse(payload)

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret")

    with pytest.raises(LookupFailure) as error:
        await client.search("query")

    assert error.value.reason == "empty_result"


async def test_search_skips_non_http_scheme_url(monkeypatch):
    payload = _web_results_payload(
        [{"Title": "File link", "Url": "file:///etc/passwd", "Summary": "s"}]
    )

    def fake_urlopen(request, timeout):
        return FakeHttpResponse(payload)

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret")

    with pytest.raises(LookupFailure) as error:
        await client.search("query")

    assert error.value.reason == "empty_result"


async def test_search_raises_when_response_exceeds_size_cap(monkeypatch):
    oversized_body = b"a" * (byte_web_search._MAX_RESPONSE_BYTES + 1)

    def fake_urlopen(request, timeout):
        return FakeHttpResponse(raw_body=oversized_body)

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret")

    with pytest.raises(ByteWebSearchError):
        await client.search("query")


async def test_search_respects_top_k_truncation(monkeypatch):
    payload = _web_results_payload(
        [
            {"Title": f"Result {i}", "Url": f"https://example.com/{i}", "Summary": "s"}
            for i in range(5)
        ]
    )

    def fake_urlopen(request, timeout):
        return FakeHttpResponse(payload)

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret")

    evidence = await client.search("query", top_k=2)

    assert len(evidence.results) == 2


async def test_search_empty_web_results_returns_typed_failure(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeHttpResponse(_web_results_payload([]))

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret")

    with pytest.raises(LookupFailure) as error:
        await client.search("query")

    assert error.value.reason == "empty_result"


async def test_search_skips_item_missing_title(monkeypatch):
    payload = _web_results_payload(
        [
            {"Title": "", "Url": "https://example.com/1", "Summary": "s"},
            {"Title": "Has title", "Url": "https://example.com/2", "Summary": "s"},
        ]
    )

    def fake_urlopen(request, timeout):
        return FakeHttpResponse(payload)

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret")

    evidence = await client.search("query")

    assert len(evidence.results) == 1
    assert evidence.results[0].title == "Has title"


async def test_search_skips_item_missing_url(monkeypatch):
    payload = _web_results_payload(
        [
            {"Title": "No url", "Url": "", "Summary": "s"},
            {"Title": "Has url", "Url": "https://example.com/2", "Summary": "s"},
        ]
    )

    def fake_urlopen(request, timeout):
        return FakeHttpResponse(payload)

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret")

    evidence = await client.search("query")

    assert len(evidence.results) == 1
    assert evidence.results[0].title == "Has url"


async def test_search_skips_non_dict_item(monkeypatch):
    payload = _web_results_payload(
        ["not-a-dict", {"Title": "Has title", "Url": "https://example.com/2", "Summary": "s"}]
    )

    def fake_urlopen(request, timeout):
        return FakeHttpResponse(payload)

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret")

    evidence = await client.search("query")

    assert len(evidence.results) == 1
    assert evidence.results[0].title == "Has title"


async def test_search_raises_on_malformed_json(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeHttpResponse(raw_body=b"not json")

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret")

    with pytest.raises(ByteWebSearchError):
        await client.search("query")


async def test_search_raises_when_result_field_missing(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeHttpResponse({"NotResult": {}})

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret")

    with pytest.raises(ByteWebSearchError):
        await client.search("query")


async def test_search_raises_when_web_results_is_not_a_list(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeHttpResponse({"Result": {"WebResults": "not-a-list"}})

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret")

    with pytest.raises(ByteWebSearchError):
        await client.search("query")


async def test_search_raises_on_network_error(monkeypatch):
    import urllib.error

    def fake_urlopen(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(byte_web_search.urllib.request, "urlopen", fake_urlopen)
    client = ByteWebSearch(api_key="secret")

    with pytest.raises(ByteWebSearchError):
        await client.search("query")
