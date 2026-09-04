---
status: accepted
---

# Preserve OpenTalking-compatible motion parameters behind runtime capability states

Digital Human Studio creates reusable Motion Base Videos offline. Completion latency is secondary to motion naturalness, identity stability, reproducibility, and the ability to retain detailed motion-transfer intent. OpenTalking exposes a richer parameter surface than OpenRealtime's current official LivePortrait command wrapper, while some OpenTalking controls belong to audio-driven mouth motion rather than the closed-mouth non-verbal Motion Base produced here.

OpenRealtime will use a versioned, OpenTalking-compatible Motion Transfer Profile as its canonical configuration boundary. It will not store only the small subset accepted by one runtime and will not pass an untyped provider configuration directly into generation.

Every profile field has one explicit Motion Parameter Compatibility state:

- `native`: the bound runtime executes the field directly;
- `offline extension`: a versioned OpenRealtime motion-template transformation executes the field without claiming numerical equivalence to FasterLivePortrait, OmniRT, or another runtime;
- `retained inactive`: the field and original value remain available for audit and interchange, but the current non-verbal Motion Base boundary prohibits execution;
- `unknown`: the field is preserved losslessly but is not executed because OpenRealtime cannot identify its semantics.

The first release includes experimental offline extensions for independent head, pose, yaw, pitch, roll, and non-verbal expression amplitudes. A user may change several parameters without triggering generation. They must manually submit one three-second Test Preview for the current complete parameter snapshot and confirm that result before full generation becomes available. Changing any effective parameter invalidates that confirmation. Tasks and candidates record the complete profile snapshot, compatibility states, runtime identity, and extension implementation version.

Speech-mouth controls remain retained inactive in this workflow. Audio following or CFG scale, mouth-open and speech-oriented mouth-corner controls, speech-related cheek or jaw motion, and lip retargeting never execute while producing the Motion Base. The downstream Lip-sync Model remains the only component that creates speaking mouth motion from actual reply audio.

Motion Profile Interchange accepts YAML and JSON. Import first creates a non-mutating Parameter Mapping Report that lists native effective, experimental effective, retained inactive, and unknown fields with their original names and values. Only explicit confirmation applies the reviewed mapping atomically to the Studio Draft. Parse failure, cancellation, or closing the report leaves the draft unchanged. Effective fields are editable only through typed controls; raw YAML or JSON is read-only. Export retains inactive and unknown fields so a supported round trip does not silently discard configuration.

The main Advanced Motion Configuration surface shows only effective typed controls. Inactive and unknown fields appear in read-only compatibility details with a reason. Saving a named configuration or applying it to a draft copies a versioned snapshot rather than creating a live link. A runtime capability change may make fields effective or inactive in a future task, but it never rewrites the compatibility state or observed result of an existing task or candidate.

FasterLivePortrait or OmniRT may be added later as another runtime binding, but neither is required to preserve OpenTalking-compatible profiles. Each runtime must declare and test its own field mapping. A stored field is never represented as effective merely because another runtime recognizes a similarly named parameter.

## Consequences

- OpenTalking-derived configurations can be imported, audited, and exported without reducing them to today's LivePortrait wrapper.
- OpenRealtime can improve or replace the offline runtime without migrating every saved profile to a provider-specific schema.
- Users see which values actually affect generation and cannot accidentally rely on ignored controls.
- Closed-mouth Motion Base ownership remains separate from downstream lip-sync ownership.
- Profiles and candidates require versioned compatibility metadata, and each runtime mapping needs conformance tests.
- Experimental offline extensions add validation and maintenance cost and may produce results that differ numerically from OpenTalking even when labels are similar.
- Unknown or inactive fields increase stored metadata size, but this cost is accepted in exchange for lossless interchange and future compatibility.

## Rejected alternatives

- **Persist only official LivePortrait native fields.** Simpler initially, but lossy for imported OpenTalking profiles and costly to reverse when another runtime is introduced.
- **Expose raw OpenTalking YAML or JSON as the editor and pass it through.** Preserves syntax but cannot guarantee that controls are effective, safe, typed, or compatible with the non-verbal mouth boundary.
- **Require FasterLivePortrait or OmniRT before supporting advanced configuration.** Couples the product configuration model to one unavailable or replaceable runtime even though offline speed is not the primary constraint.
- **Execute speech-mouth parameters and suppress them later.** Creates conflicting mouth ownership, contaminates the Motion Base with speaking articulation, and makes downstream lip-sync less predictable.
