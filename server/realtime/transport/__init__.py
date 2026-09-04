"""Transport adapters for the provider-neutral Realtime protocol."""

from server.realtime.transport.websocket import RealtimeWebSocketFrameBridge

__all__ = ["RealtimeWebSocketFrameBridge"]
