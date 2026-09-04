"""Input signals Turn Policy consumes, and the R-actions it can emit.

Signals are decoupled from any specific VAD/EoT/overlap-detector
implementation — see CONTEXT.md's Turn Policy entry ("these are
inputs/signals Turn Policy consumes, not the Seam itself"). Each signal maps
to one transition (τ1-τ11) from docs/full-duplex-survey.md §4.2, except
CONCURRENT_SPEECH which drives the DUAL self-loop noted in that section.
"""

from __future__ import annotations

from enum import Enum


class Signal(Enum):
    USER_SPEECH_ONSET = "user_speech_onset"  # τ1
    PROACTIVE_TIMER = "proactive_timer"  # τ2
    USER_EOT_CONFIRMED = "user_eot_confirmed"  # τ3, τ5
    USER_SPEECH_ABORTED = "user_speech_aborted"
    # Acoustic speech ended without any transcript. This releases LISTEN while
    # allowing a late ASR revision to claim the floor as a fresh onset.
    USER_HESITATION = "user_hesitation"  # τ4
    USER_RESUMED = "user_resumed"  # τ6
    SYSTEM_EOT = "system_eot"  # τ7
    OVERLAP_DETECTED = "overlap_detected"  # τ8
    FLOOR_CLAIM = "floor_claim"  # τ9
    BACKCHANNEL = "backchannel"  # τ10
    THIRD_PARTY = "third_party"  # τ11
    CONCURRENT_SPEECH = "concurrent_speech"  # DUAL self-loop
    SEMANTIC_TURN_SUPPRESSED = "semantic_turn_suppressed"
    # A control-only interruption (stop/backchannel/ignore/uncertain) reached
    # its terminal ASR boundary. It closes LISTEN without creating a Brain turn.


class ResponseAction(Enum):
    RESPOND = "respond"  # R6
    YIELD = "yield"  # R2
    CONTINUE = "continue"  # R1
    WAIT = "wait"  # R3
    IGNORE = "ignore"  # R5
