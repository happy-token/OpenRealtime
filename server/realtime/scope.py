"""Identity helpers shared across Realtime conversation seams."""

from server.core.interaction_context import InteractionContext


def conversation_scope(context: InteractionContext) -> tuple[str, str, str, str, str]:
    return (
        context.tenant_id,
        context.user_id,
        context.device_id,
        context.voice_session_id,
        context.thread_id,
    )
