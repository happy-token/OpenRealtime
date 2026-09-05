# Exclude head-pose transfer from LivePortrait by default

LivePortrait can transfer head pose, but in the static-image segmented-rendering workflow the avatar's head and body must stay at the source pose, so `animation_region` defaults to `"exp"` (expression-only) rather than `"all"`.

Head pose is the most artifact-prone axis of LivePortrait's motion model, and body motion is never transferred (the body is pasted from the static source). A reference Natural Interaction Performance with even slight body drift causes the face to slide across the crop, and that `t`/global-translation component transfers onto a body that never moves — producing the distinctive "head slides, body doesn't" incoherence. Restricting transfer to facial expression removes that failure mode by construction, and makes `driving_multiplier` an expression-intensity knob rather than a whole-motion scalar.

Deliberately not chosen: separating a `t`-damp custom inference path (over-engineered for the goal), a head-motion admission gate (unnecessary once pose isn't transferred), or a runtime that transfers head pose more stably (later product decision; ADR-0073 already allows FastLivePortrait/OmniRT as future bindings).
