"""Turn Policy: the Seam owning dialogue-state management.

Implements the five-state / eleven-transition FSM from
docs/full-duplex-survey.md §4. τ1 (onset) and τ11 (third-party ignore) are
gated by an AddresseeClassifier (ADR-0004); τ1 is additionally gated by an
optional WakeWordDetector (ADR-0005) — both must allow it to fire, since the
two plugins answer independent questions ("is this the wake word?" vs. "is
this addressed to the assistant?"). τ11 stays AddresseeClassifier-only, per
ADR-0005's explicit scoping. Every other transition is unconditional given
its triggering Signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from server.turn_policy.addressee import AddresseeClassifier, DefaultAddresseeClassifier
from server.turn_policy.signals import ResponseAction, Signal
from server.turn_policy.states import DialogueState
from server.turn_policy.wake_word import NoWakeWordGating, WakeWordDetector


@dataclass(frozen=True)
class Transition:
    name: str
    to_state: DialogueState
    action: ResponseAction | None


class DialoguePolicy(Protocol):
    """Session-local dialogue state authority, independent of the FSM algorithm.

    Implementations expose canonical states/signals so Turn Manager can retain
    its endpoint and interruption guards while replacing transition decisions.
    A factory must create a fresh instance for each conversation.
    """

    @property
    def state(self) -> DialogueState: ...

    async def evaluate(self, signal: Signal, *, generation: int) -> Transition | None: ...


_TABLE: dict[tuple[DialogueState, Signal], Transition] = {
    (DialogueState.IDLE, Signal.PROACTIVE_TIMER): Transition(
        "τ2", DialogueState.SPEAK, ResponseAction.RESPOND
    ),
    (DialogueState.LISTEN, Signal.USER_EOT_CONFIRMED): Transition(
        "τ3", DialogueState.SPEAK, ResponseAction.RESPOND
    ),
    (DialogueState.LISTEN, Signal.USER_SPEECH_ABORTED): Transition(
        "speech_aborted", DialogueState.IDLE, None
    ),
    (DialogueState.LISTEN, Signal.USER_HESITATION): Transition(
        "τ4", DialogueState.WAIT, ResponseAction.WAIT
    ),
    (DialogueState.WAIT, Signal.USER_EOT_CONFIRMED): Transition(
        "τ5", DialogueState.SPEAK, ResponseAction.RESPOND
    ),
    (DialogueState.WAIT, Signal.USER_RESUMED): Transition("τ6", DialogueState.LISTEN, None),
    (DialogueState.SPEAK, Signal.SYSTEM_EOT): Transition("τ7", DialogueState.IDLE, None),
    (DialogueState.SPEAK, Signal.OVERLAP_DETECTED): Transition("τ8", DialogueState.DUAL, None),
    (DialogueState.DUAL, Signal.FLOOR_CLAIM): Transition(
        "τ9", DialogueState.LISTEN, ResponseAction.YIELD
    ),
    (DialogueState.DUAL, Signal.BACKCHANNEL): Transition(
        "τ10", DialogueState.SPEAK, ResponseAction.CONTINUE
    ),
    (DialogueState.DUAL, Signal.CONCURRENT_SPEECH): Transition(
        "dual_self_loop", DialogueState.DUAL, ResponseAction.CONTINUE
    ),
    (DialogueState.LISTEN, Signal.SEMANTIC_TURN_SUPPRESSED): Transition(
        "semantic_suppress", DialogueState.IDLE, None
    ),
    (DialogueState.WAIT, Signal.SEMANTIC_TURN_SUPPRESSED): Transition(
        "semantic_suppress", DialogueState.IDLE, None
    ),
}

_TAU1 = Transition("τ1", DialogueState.LISTEN, None)
_TAU11 = Transition("τ11", DialogueState.SPEAK, ResponseAction.IGNORE)


class TurnPolicy:
    def __init__(
        self,
        addressee_classifier: AddresseeClassifier | None = None,
        wake_word_detector: WakeWordDetector | None = None,
    ) -> None:
        self._state = DialogueState.IDLE
        self._addressee_classifier = addressee_classifier or DefaultAddresseeClassifier()
        self._wake_word_detector = wake_word_detector or NoWakeWordGating()

    @property
    def state(self) -> DialogueState:
        return self._state

    async def evaluate(self, signal: Signal, *, generation: int) -> Transition | None:
        """Evaluate one input signal against the current state.

        Returns the Transition taken, or None if the signal has no rule from
        the current state, or was vetoed by the AddresseeClassifier or (for
        τ1 only) the WakeWordDetector — all are no-ops, not errors.
        """
        if signal is Signal.USER_SPEECH_ONSET and self._state is DialogueState.IDLE:
            return await self._evaluate_onset(generation=generation)
        if signal is Signal.THIRD_PARTY and self._state is DialogueState.DUAL:
            return await self._evaluate_third_party(generation=generation)

        transition = _TABLE.get((self._state, signal))
        if transition is None:
            return None
        self._state = transition.to_state
        return transition

    async def _evaluate_onset(self, *, generation: int) -> Transition | None:
        if not await self._wake_word_detector.is_wake_event(generation=generation):
            return None
        if not await self._addressee_classifier.is_addressed(generation=generation):
            return None
        self._state = _TAU1.to_state
        return _TAU1

    async def _evaluate_third_party(self, *, generation: int) -> Transition | None:
        if await self._addressee_classifier.is_addressed(generation=generation):
            return None
        self._state = _TAU11.to_state
        return _TAU11
