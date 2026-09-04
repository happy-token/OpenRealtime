"""Loopback-only HTTP adapter for :mod:`server.avatar_assets.service`."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs

from server.avatar_assets.models import (
    AcceptanceChecks,
    CandidateConflict,
    CandidateSourceKind,
    LoopWindow,
    WorkInProgress,
)
from server.avatar_assets.service import AvatarAssetService

_ACCEPT_PATH = re.compile(r"^/avatar-assets/candidates/(?P<id>[^/]+)/accept$")
_APPROVE_PATH = re.compile(r"^/avatar-assets/renditions/(?P<id>[^/]+)/approve$")
_ARTIFACT_PATH = re.compile(r"^/avatar-assets/artifacts/(?P<id>[^/]+)$")


@dataclass(frozen=True, slots=True)
class AvatarAssetHttpResponse:
    status: int
    body: bytes
    content_type: str = "application/json; charset=utf-8"
    headers: Mapping[str, str] | None = None

    @classmethod
    def json(cls, status: int, payload: object) -> AvatarAssetHttpResponse:
        return cls(status, json.dumps(payload).encode("utf-8"))


class AvatarAssetHttpApi:
    def __init__(self, service: AvatarAssetService) -> None:
        self._service = service

    async def handle(
        self,
        method: str,
        path: str,
        query: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> AvatarAssetHttpResponse:
        try:
            return await self._handle(method, path, query, headers, body)
        except KeyError:
            return AvatarAssetHttpResponse.json(404, {"error": "avatar asset not found"})
        except WorkInProgress:
            return AvatarAssetHttpResponse.json(409, {"error": "avatar asset work is in progress"})
        except CandidateConflict as error:
            return AvatarAssetHttpResponse.json(409, {"error": str(error)})
        except (TypeError, ValueError) as error:
            return AvatarAssetHttpResponse.json(400, {"error": str(error)})

    async def _handle(
        self,
        method: str,
        path: str,
        query: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> AvatarAssetHttpResponse:
        if method == "POST" and path == "/avatar-assets/candidates/upload":
            parameters = parse_qs(query, keep_blank_values=True)
            media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            payload = await self._service.upload_candidate(
                avatar_id=_one(parameters, "avatar_id"),
                source_kind=CandidateSourceKind(_one(parameters, "source_kind")),
                source_id=_one(parameters, "source_id"),
                logical_name=_one(parameters, "logical_name"),
                media_type=media_type,
                rights_scope=_one(parameters, "rights_scope"),
                idempotency_key=_one(parameters, "idempotency_key"),
                data=body,
            )
            return AvatarAssetHttpResponse.json(201, payload)

        match = _ACCEPT_PATH.match(path)
        if method == "POST" and match is not None:
            payload = _json_object(body)
            checks = payload.get("checks")
            if not isinstance(checks, dict):
                raise ValueError("checks must be an object")
            result = await self._service.accept_candidate(
                match.group("id"),
                checks=AcceptanceChecks(
                    identity_match=_boolean(checks, "identity_match"),
                    single_person=_boolean(checks, "single_person"),
                    closed_mouth=_boolean(checks, "closed_mouth"),
                    fixed_camera=_boolean(checks, "fixed_camera"),
                    no_gestures=_boolean(checks, "no_gestures"),
                    rights_confirmed=_boolean(checks, "rights_confirmed"),
                ),
                idempotency_key=_string(payload, "idempotency_key"),
            )
            return AvatarAssetHttpResponse.json(200, result)

        if method == "GET" and path == "/avatar-assets/actions":
            parameters = parse_qs(query, keep_blank_values=True)
            result = await self._service.list_avatar_actions(
                _optional_one(parameters, "avatar_id")
            )
            return AvatarAssetHttpResponse.json(200, result)

        match = _APPROVE_PATH.match(path)
        if method == "POST" and match is not None:
            payload = _json_object(body)
            result = await self._service.approve_rendition(
                match.group("id"),
                loop=LoopWindow(
                    start_ms=_integer(payload, "start_ms"),
                    end_ms=_integer(payload, "end_ms"),
                    crossfade_ms=_integer(payload, "crossfade_ms"),
                ),
            )
            return AvatarAssetHttpResponse.json(200, result)

        if method == "POST" and path == "/avatar-assets/selections":
            payload = _json_object(body)
            result = await self._service.select_avatar_action(
                _string(payload, "avatar_id"),
                _string(payload, "avatar_action_id"),
            )
            return AvatarAssetHttpResponse.json(200, result)

        match = _ARTIFACT_PATH.match(path)
        if method == "GET" and match is not None:
            data, media_type = await self._service.read_artifact(match.group("id"))
            response_headers = {
                "Accept-Ranges": "bytes",
                "Cache-Control": "private, max-age=3600, immutable",
                "X-Content-Type-Options": "nosniff",
            }
            range_header = headers.get("range") or headers.get("Range")
            if range_header:
                byte_range = _parse_byte_range(range_header, len(data))
                if byte_range is None:
                    return AvatarAssetHttpResponse(
                        416,
                        b"",
                        media_type,
                        {**response_headers, "Content-Range": f"bytes */{len(data)}"},
                    )
                start, end = byte_range
                return AvatarAssetHttpResponse(
                    206,
                    data[start : end + 1],
                    media_type,
                    {
                        **response_headers,
                        "Content-Range": f"bytes {start}-{end}/{len(data)}",
                    },
                )
            return AvatarAssetHttpResponse(
                200,
                data,
                media_type,
                response_headers,
            )

        return AvatarAssetHttpResponse.json(404, {"error": "not found"})


def _one(parameters: Mapping[str, list[str]], field: str) -> str:
    values = parameters.get(field)
    if values is None or len(values) != 1 or not values[0]:
        raise ValueError(f"{field} must appear exactly once")
    return values[0]


def _parse_byte_range(value: str, size: int) -> tuple[int, int] | None:
    if not value.startswith("bytes=") or "," in value or size <= 0:
        return None
    bounds = value[6:].split("-", 1)
    if len(bounds) != 2:
        return None
    start_text, end_text = bounds
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
            if start < 0 or start >= size or end < start:
                return None
            return start, min(end, size - 1)
        suffix_length = int(end_text)
        if suffix_length <= 0:
            return None
        return max(0, size - suffix_length), size - 1
    except ValueError:
        return None


def _optional_one(parameters: Mapping[str, list[str]], field: str) -> str | None:
    values = parameters.get(field)
    if values is None:
        return None
    if len(values) != 1 or not values[0]:
        raise ValueError(f"{field} must appear at most once")
    return values[0]


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("invalid json body") from error
    if not isinstance(payload, dict):
        raise TypeError("json body must be an object")
    return payload


def _string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _boolean(payload: Mapping[str, Any], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be a boolean")
    return value


def _integer(payload: Mapping[str, Any], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field} must be an integer")
    return value
