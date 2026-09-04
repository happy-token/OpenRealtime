"""Errors shared by Realtime control-plane and engine adapters."""


class ContextVisibilityError(RuntimeError):
    """Raised when a response requests context the engine has not projected."""
