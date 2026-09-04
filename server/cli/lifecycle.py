"""Dependency-free helpers for sync or async application lifecycle hooks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Any


LifecycleHook = Callable[..., Any | Awaitable[Any]]


async def invoke_lifecycle_hook(
    hook: LifecycleHook | None,
    *args: object,
) -> Any:
    if hook is None:
        return None
    result = hook(*args)
    if isawaitable(result):
        return await result
    return result
