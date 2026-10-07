"""Actor-issued permission to replace a reply without admitting a new input."""

from dataclasses import dataclass

from server.core.interaction_context import InteractionContext

MAX_CONTEXT_REPAIRS = 2


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplyRepairPermit:
    permit_id: str
    context: InteractionContext
    predecessor_response_id: str
    response_id: str
    input_id: str
    input_version: int
    predecessor_reply_version: int
    minimum_thread_sequence: int
    attempt: int
    deadline_ns: int

    def __post_init__(self) -> None:
        if not self.permit_id or not self.predecessor_response_id or not self.input_id or not self.response_id:
            raise ValueError("reply repair requires input, response and permission identities")
        if self.response_id == self.predecessor_response_id:
            raise ValueError("reply repair requires a new response identity")
        if min(self.input_version, self.predecessor_reply_version, self.minimum_thread_sequence, self.deadline_ns) < 1:
            raise ValueError("reply repair requires positive versions, projection and deadline")
        if not 1 <= self.attempt <= MAX_CONTEXT_REPAIRS:
            raise ValueError("reply repair attempt exceeds its bounded budget")
