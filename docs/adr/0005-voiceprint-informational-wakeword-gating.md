---
status: accepted
---

# Voiceprint is informational metadata; Wake Word is a hard gate

The two optional plugins referenced by the PRD ("唤醒" and "声纹", both non-essential) attach to the architecture in different ways rather than through one unified veto mechanism. **Wake Word** is a Hook Point on τ1 (IDLE→LISTEN): no wake event means the system stays in IDLE, mirroring how device-side wake detection (e.g. Xiaozhi's on-device model, which reports only a discrete event to the server) works in practice. **Voiceprint** is informational only: a speaker-match result (`match`/`no_match`/`unavailable`/`adaptive`) is attached to Turn Content as metadata, and the turn still proceeds to the Brain — it is never silently blocked by Turn Policy.

We considered unifying both under one hard-gate mechanism, since both are nominally "optional identity-adjacent plugins." We rejected this: our own prior voiceloop reference documentation is explicit that voiceprint matching is not general identity authentication and must not silently gate/reject on its own — mismatched or unavailable results must surface as structured status for the calling application to interpret, since voice conditions (distance, noise, cross-talk) make false rejects common enough that hard-blocking would be unsafe as a default. Wake word carries no such caveat — a missing wake event is an unambiguous "not addressed to the assistant" signal in the reference implementations we found. Treating these identically would reproduce a known misuse pattern (using a soft biometric signal as a hard authorization check), so the asymmetry is recorded here.
