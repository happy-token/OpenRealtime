---
status: accepted
---

# One AddresseeClassifier plugin gates both τ1 and τ11

Third-party-speech exclusion (PRD point 11) has two attachment points in Turn Policy, not one: τ11 (DUAL→SPEAK, ignore) handles third-party speech detected while the assistant is already speaking, but the same problem exists at τ1 (IDLE→LISTEN, user-onset) — voice detected while the assistant is idle may also not be addressed to it. Both attachment points are gated by the same `AddresseeClassifier` plugin interface rather than two separate mechanisms. When no classifier is registered, both default to treating all speech as addressed to the assistant (the conservative/safe default, since falsely ignoring real commands is worse than an occasional unnecessary LISTEN transition).

We considered leaving τ1 ungated and relying solely on a wake-word mechanism (Task #13) to control entry into real interaction, on the theory that false onsets are cheap since nothing is spoken back until the Brain actually responds. We rejected relying on wake-word alone here: wake-word is an optional plugin per the PRD ("非必要，可以插件形式存在"), so a deployment without one would have no way to suppress third-party-speech-triggered onset at all. Unifying both attachment points behind one classifier interface is not the first design a reader would guess — τ1 and τ11 look like unrelated transitions (onset vs. mid-speech) — so it's recorded here.
