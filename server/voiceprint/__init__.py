"""Voiceprint Service: embedding, matching, and enrollment for the
VoiceprintMatcher seam. See CONTEXT.md — Voiceprint, and ADR-0005/ADR-0022.

server/signals/voiceprint.py's VoiceprintMatcher Protocol and
NoVoiceprintMatching default are unchanged by this subpackage — they stay
the Kernel-facing seam. This package supplies the real conformer
(EnrolledSpeakerVoiceprintMatcher) and the pieces it's built from.
"""
