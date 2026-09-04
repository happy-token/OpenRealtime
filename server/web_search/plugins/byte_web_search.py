"""Real ByteDance ("byte") web-search conformer for the WebSearch contract.

Speaks ByteDance's search_api/web_search JSON-over-HTTPS endpoint, the same
one voiceloop's brain/byte_search.py speaks
(a sibling reference implementation) — see ADR-0016. Uses stdlib
urllib.request wrapped in asyncio.to_thread, mirroring
brain/plugins/openai_compatible_llm_client.py's OpenAiCompatibleLlmClient; no
new HTTP dependency.

The credential (BYTE_WEB_SEARCH_API_KEY) is read from the environment and
never logged or printed.

Response reads are size-capped and result URLs are validated before they
ever reach structured evidence a model might read out loud or cite —
inspired by realtime's brain/web_search.py::read_bounded_json_response /
normalize_result_url, reimplemented here rather than imported across repos
(and narrower: these URLs are only ever displayed, never fetched by this
server, so validation stays to scheme/credential/IP-literal checks with no
DNS resolution). Each normalized result carries its source host, while the
evidence envelope carries a retrieved_at timestamp so a downstream answer can
be time-qualified instead of presented as a timeless fact.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import ssl
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import urlsplit

from server.observability.telemetry import SessionTelemetry
from server.web_search.protocol import (
    LookupEvidence,
    LookupFailure,
    LookupFailureReason,
    SearchResult,
)

DEFAULT_BASE_URL = "https://open.feedcoopapi.com/search_api/web_search"

_MAX_RESPONSE_BYTES = 1_000_000
_READ_CHUNK_BYTES = 65_536
_MAX_RESULTS = 10

logger = logging.getLogger(__name__)


def resolve_search_api_key(environ: Mapping[str, str] | None = None) -> str:
    """Resolve the canonical key while accepting the VoiceLoop legacy name."""

    values = os.environ if environ is None else environ
    canonical = values.get("BYTE_WEB_SEARCH_API_KEY", "").strip()
    legacy = values.get("WEB_SEARCH_API_KEY", "").strip()
    if legacy:
        logger.warning(
            "WEB_SEARCH_API_KEY is deprecated; use BYTE_WEB_SEARCH_API_KEY"
        )
    return canonical or legacy


class ByteWebSearchError(LookupFailure):
    """Raised when the byte web-search endpoint is unreachable or replies
    with a malformed/unexpected payload."""

    def __init__(self, reason: LookupFailureReason, detail: str = "") -> None:
        super().__init__(reason, provider="byte", detail=detail)


class ByteWebSearch:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 3.0,
        max_attempts: int | None = None,
        telemetry: SessionTelemetry | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else resolve_search_api_key()
        self._base_url = base_url or os.environ.get("BYTE_WEB_SEARCH_BASE_URL") or DEFAULT_BASE_URL
        self._timeout_s = timeout_s
        self._max_attempts = (
            max_attempts
            if max_attempts is not None
            else int(os.environ.get("BYTE_WEB_SEARCH_MAX_ATTEMPTS", "3"))
        )
        if self._max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._telemetry = telemetry

    async def search(self, query: str, *, top_k: int = 3) -> LookupEvidence:
        normalized_query = query.strip()[:500]
        if not self._api_key:
            raise ByteWebSearchError("provider_unavailable", "missing API key")
        if not normalized_query:
            raise ByteWebSearchError("invalid_response", "empty query")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise ByteWebSearchError("invalid_response", "top_k must be a positive integer")
        bounded_top_k = min(top_k, _MAX_RESULTS)
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await self._search_attempt(
                    normalized_query,
                    bounded_top_k,
                    attempt=attempt,
                )
            except ByteWebSearchError as error:
                if attempt >= self._max_attempts or not _is_retryable(error):
                    raise
        raise AssertionError("search retry loop exhausted without a result")

    async def _search_attempt(
        self,
        query: str,
        top_k: int,
        *,
        attempt: int,
    ) -> LookupEvidence:
        if self._telemetry is None:
            return await asyncio.to_thread(self._search_sync, query, top_k)
        async with self._telemetry.provider_call(
            provider="byte",
            operation="web_search",
            timeout_ms=self._timeout_s * 1000,
            attempt=attempt,
            attributes={"query_length": len(query), "top_k": top_k},
        ) as call:
            evidence = await asyncio.to_thread(self._search_sync, query, top_k)
            call.mark_first_response()
            return evidence

    def _search_sync(self, query: str, top_k: int) -> LookupEvidence:
        body = json.dumps(
            {"Query": query, "SearchType": "web", "Count": top_k, "NeedSummary": True}
        ).encode("utf-8")
        request = urllib.request.Request(
            self._base_url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "x-traffic-tag": "skill_web_search_common",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                parsed = _read_bounded_json(response)
        except TimeoutError as exc:
            raise ByteWebSearchError("timeout", str(exc)) from exc
        except urllib.error.HTTPError as exc:
            raise ByteWebSearchError("http_error", f"HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            reason = "timeout" if isinstance(exc.reason, TimeoutError) else "http_error"
            raise ByteWebSearchError(reason, str(exc)) from exc

        result_node = parsed.get("Result") if isinstance(parsed, dict) else None
        raw_results = result_node.get("WebResults") if isinstance(result_node, dict) else None
        if not isinstance(raw_results, list):
            raise ByteWebSearchError(
                "invalid_response",
                "byte web search returned an unexpected response shape",
            )

        retrieved_at = datetime.now(UTC).isoformat()
        results: list[SearchResult] = []
        for item in raw_results[:top_k]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("Title") or "").strip()[:200]
            url = str(item.get("Url") or "").strip()
            summary = str(item.get("Summary") or item.get("Snippet") or "").strip()[:2000]
            if not title or not url or not _is_safe_public_url(url):
                continue
            site = urlsplit(url).hostname or ""
            published_at = str(
                item.get("DatePublished") or item.get("PublishedAt") or ""
            ).strip()[:100]
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    summary=summary,
                    source=site,
                    published_at=published_at or None,
                )
            )
        if not results:
            raise ByteWebSearchError("empty_result")
        return LookupEvidence(
            provider="byte",
            query=query,
            results=tuple(results),
            retrieved_at=retrieved_at,
        )


def _read_bounded_json(response: object, *, limit: int = _MAX_RESPONSE_BYTES) -> object:
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        chunk = response.read(_READ_CHUNK_BYTES)  # type: ignore[attr-defined]
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > limit:
            raise ByteWebSearchError(
                "invalid_response",
                f"byte web search response exceeded {limit} bytes",
            )
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks))
    except (TypeError, ValueError) as exc:
        raise ByteWebSearchError(
            "invalid_response",
            "byte web search returned invalid JSON",
        ) from exc


def _is_retryable(error: ByteWebSearchError) -> bool:
    if error.reason == "timeout":
        return True
    cause = error.__cause__
    if isinstance(cause, urllib.error.HTTPError):
        return cause.code == 429 or 500 <= cause.code < 600
    if isinstance(cause, urllib.error.URLError):
        cause = cause.reason
    return isinstance(
        cause,
        (
            ssl.SSLError,
            ConnectionError,
            TimeoutError,
        ),
    )


def _is_safe_public_url(url: str) -> bool:
    """Rejects non-http(s) schemes, embedded credentials, and any raw IP
    literal in a private/loopback/link-local/reserved range. These URLs are
    only ever displayed as citations, never fetched by this server, so this
    deliberately skips DNS resolution for domain names — that would add an
    unreliable network call to a validation step without closing any real
    request-forgery path."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.hostname or parsed.username or parsed.password:
        return False
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return True
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_multicast
    )
