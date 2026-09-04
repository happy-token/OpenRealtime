# Digital-human preview assets (not distributed)

This directory intentionally ships **empty** in the open-source release. The
original directory held ~150 files (~180 MB) of realistic-person preview
images and idle/talking videos used by the avatar UI — excluded here because
this project doesn't own redistribution rights to those portraits/voices, not
because the feature is unsupported.

None of this matters unless you explicitly opt in: avatar rendering defaults
to `OPENREALTIME_AVATAR_RENDERER_MODE=disabled` (see `.env.example`), and
without it the code paths that read from this directory are never reached.
See [ISSUE-0028](../../docs/ISSUES.md#issue-0028-publicdigital-human-preview-assets-are-not-distributed-with-the-open-source-release)
for the current state of that fallback behavior.

If you want the avatar preview UI to render for real, supply your own assets
at the same paths the code expects. The subdirectories the app looks for:

- `builtin-motion/` — built-in idle/talking loop videos + poster frames
  (e.g. `liveportrait-optimized.mp4` + a matching `.jpg` poster,
  `avatar-bundled.mp4`, `shuchang-realtime-idle.mp4`).
- `liveportrait-actions/` — short action clips keyed by name (e.g.
  `cool-night.mp4`, `gentle-intellectual.mp4`, `soft-glow.mp4`,
  `sweet-vitality.mp4`, `melancholy-empathy.mp4`).
- `opentalking/<character>/` — one folder per built-in character, each with
  its own `motion.mp4`, `preview.png`, and `reference.png` (see
  `src/lib/builtin-avatar-actions.ts` for the current character list).
- `portrait-library/` — a larger curated/experimental portrait set
  (`selected/`, `experiments/`, `legacy/`, `styles/`).
- `styles/` — style-transfer reference images grouped by look.
- Top-level static images referenced directly, e.g. `avatar1.png`,
  `avatar2.png`, `shaliu.png`, `shuchang.png`, `shuchang-preview.jpg`.

Any path not listed above but referenced from `src/components/digital-human/**`
or `src/lib/avatar-renderer-preparation.ts` follows the same pattern: the
literal string after `/digital-human/` in the source is the path this
directory needs to provide.
