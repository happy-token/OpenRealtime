from server.turn_policy.policy import TurnPolicy
from server.turn_policy.signals import ResponseAction, Signal
from server.turn_policy.states import DialogueState


class RejectingClassifier:
    """Test double: always says speech is not addressed to the assistant."""

    async def is_addressed(self, *, generation: int) -> bool:
        return False


class RejectingWakeWordDetector:
    """Test double: never detects a wake event."""

    async def is_wake_event(self, *, generation: int) -> bool:
        return False


class AllowingWakeWordDetector:
    """Test double: always detects a wake event."""

    async def is_wake_event(self, *, generation: int) -> bool:
        return True


async def test_starts_in_idle():
    policy = TurnPolicy()

    assert policy.state is DialogueState.IDLE


async def test_tau1_idle_to_listen_on_user_onset():
    policy = TurnPolicy()

    transition = await policy.evaluate(Signal.USER_SPEECH_ONSET, generation=1)

    assert transition is not None
    assert transition.name == "τ1"
    assert policy.state is DialogueState.LISTEN


async def test_tau1_vetoed_by_addressee_classifier_stays_idle():
    policy = TurnPolicy(addressee_classifier=RejectingClassifier())

    transition = await policy.evaluate(Signal.USER_SPEECH_ONSET, generation=1)

    assert transition is None
    assert policy.state is DialogueState.IDLE


async def test_tau1_allowed_when_wake_word_detector_detects_wake_event():
    policy = TurnPolicy(wake_word_detector=AllowingWakeWordDetector())

    transition = await policy.evaluate(Signal.USER_SPEECH_ONSET, generation=1)

    assert transition is not None
    assert transition.name == "τ1"
    assert policy.state is DialogueState.LISTEN


async def test_tau1_vetoed_by_wake_word_detector_stays_idle():
    policy = TurnPolicy(wake_word_detector=RejectingWakeWordDetector())

    transition = await policy.evaluate(Signal.USER_SPEECH_ONSET, generation=1)

    assert transition is None
    assert policy.state is DialogueState.IDLE


async def test_tau1_requires_both_wake_word_and_addressee_to_pass():
    # Wake word allows, but addressee vetoes -> still blocked.
    policy = TurnPolicy(
        addressee_classifier=RejectingClassifier(),
        wake_word_detector=AllowingWakeWordDetector(),
    )

    transition = await policy.evaluate(Signal.USER_SPEECH_ONSET, generation=1)

    assert transition is None
    assert policy.state is DialogueState.IDLE


async def test_tau1_requires_wake_word_even_when_addressee_allows():
    # Addressee allows, but wake word vetoes -> still blocked.
    policy = TurnPolicy(wake_word_detector=RejectingWakeWordDetector())

    transition = await policy.evaluate(Signal.USER_SPEECH_ONSET, generation=1)

    assert transition is None
    assert policy.state is DialogueState.IDLE


async def test_tau11_unaffected_by_wake_word_detector():
    # τ11 stays AddresseeClassifier-only, per ADR-0005's explicit scoping —
    # a rejecting WakeWordDetector must not veto third-party-speech ignore.
    policy = TurnPolicy(
        addressee_classifier=RejectingClassifier(),
        wake_word_detector=RejectingWakeWordDetector(),
    )
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    await policy.evaluate(Signal.OVERLAP_DETECTED, generation=1)

    transition = await policy.evaluate(Signal.THIRD_PARTY, generation=1)

    assert transition.name == "τ11"
    assert policy.state is DialogueState.SPEAK


async def test_tau2_idle_to_speak_on_proactive_timer():
    policy = TurnPolicy()

    transition = await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)

    assert transition.name == "τ2"
    assert policy.state is DialogueState.SPEAK
    assert transition.action is ResponseAction.RESPOND


async def test_tau3_listen_to_speak_on_eot_confirmed():
    policy = TurnPolicy()
    await policy.evaluate(Signal.USER_SPEECH_ONSET, generation=1)

    transition = await policy.evaluate(Signal.USER_EOT_CONFIRMED, generation=1)

    assert transition.name == "τ3"
    assert policy.state is DialogueState.SPEAK


async def test_tau4_listen_to_wait_on_hesitation():
    policy = TurnPolicy()
    await policy.evaluate(Signal.USER_SPEECH_ONSET, generation=1)

    transition = await policy.evaluate(Signal.USER_HESITATION, generation=1)

    assert transition.name == "τ4"
    assert policy.state is DialogueState.WAIT
    assert transition.action is ResponseAction.WAIT


async def test_tau5_wait_to_speak_on_eot_reconfirmed():
    policy = TurnPolicy()
    await policy.evaluate(Signal.USER_SPEECH_ONSET, generation=1)
    await policy.evaluate(Signal.USER_HESITATION, generation=1)

    transition = await policy.evaluate(Signal.USER_EOT_CONFIRMED, generation=1)

    assert transition.name == "τ5"
    assert policy.state is DialogueState.SPEAK


async def test_tau6_wait_to_listen_on_user_resumes():
    policy = TurnPolicy()
    await policy.evaluate(Signal.USER_SPEECH_ONSET, generation=1)
    await policy.evaluate(Signal.USER_HESITATION, generation=1)

    transition = await policy.evaluate(Signal.USER_RESUMED, generation=1)

    assert transition.name == "τ6"
    assert policy.state is DialogueState.LISTEN


async def test_tau7_speak_to_idle_on_system_eot():
    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)

    transition = await policy.evaluate(Signal.SYSTEM_EOT, generation=1)

    assert transition.name == "τ7"
    assert policy.state is DialogueState.IDLE


async def test_tau8_speak_to_dual_on_overlap_detected():
    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)

    transition = await policy.evaluate(Signal.OVERLAP_DETECTED, generation=1)

    assert transition.name == "τ8"
    assert policy.state is DialogueState.DUAL


async def test_tau9_dual_to_listen_on_floor_claim():
    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    await policy.evaluate(Signal.OVERLAP_DETECTED, generation=1)

    transition = await policy.evaluate(Signal.FLOOR_CLAIM, generation=1)

    assert transition.name == "τ9"
    assert policy.state is DialogueState.LISTEN
    assert transition.action is ResponseAction.YIELD


async def test_tau10_dual_to_speak_on_backchannel_continues():
    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    await policy.evaluate(Signal.OVERLAP_DETECTED, generation=1)

    transition = await policy.evaluate(Signal.BACKCHANNEL, generation=1)

    assert transition.name == "τ10"
    assert policy.state is DialogueState.SPEAK
    assert transition.action is ResponseAction.CONTINUE


async def test_tau11_dual_to_speak_on_third_party_ignored_when_not_addressed():
    policy = TurnPolicy(addressee_classifier=RejectingClassifier())
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    await policy.evaluate(Signal.OVERLAP_DETECTED, generation=1)

    transition = await policy.evaluate(Signal.THIRD_PARTY, generation=1)

    assert transition.name == "τ11"
    assert policy.state is DialogueState.SPEAK
    assert transition.action is ResponseAction.IGNORE


async def test_tau11_vetoed_when_addressee_classifier_says_addressed():
    policy = TurnPolicy()  # default classifier: always addressed
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    await policy.evaluate(Signal.OVERLAP_DETECTED, generation=1)

    transition = await policy.evaluate(Signal.THIRD_PARTY, generation=1)

    assert transition is None
    assert policy.state is DialogueState.DUAL


async def test_dual_self_loop_on_concurrent_speech():
    policy = TurnPolicy()
    await policy.evaluate(Signal.PROACTIVE_TIMER, generation=1)
    await policy.evaluate(Signal.OVERLAP_DETECTED, generation=1)

    transition = await policy.evaluate(Signal.CONCURRENT_SPEECH, generation=1)

    assert transition.name == "dual_self_loop"
    assert policy.state is DialogueState.DUAL


async def test_unhandled_signal_from_current_state_is_a_noop():
    policy = TurnPolicy()

    transition = await policy.evaluate(Signal.FLOOR_CLAIM, generation=1)

    assert transition is None
    assert policy.state is DialogueState.IDLE


async def test_semantic_control_only_turn_closes_listen_without_response():
    policy = TurnPolicy()
    await policy.evaluate(Signal.USER_SPEECH_ONSET, generation=1)

    transition = await policy.evaluate(
        Signal.SEMANTIC_TURN_SUPPRESSED,
        generation=1,
    )

    assert transition is not None
    assert transition.name == "semantic_suppress"
    assert transition.action is None
    assert policy.state is DialogueState.IDLE
