# README visual assets

Created 2026-10-12 for the English and Chinese project READMEs.

- `hero-*.svg`: editable, self-contained brand artwork. The waveform is an illustration, not a latency or audio-quality measurement.
- `agent-map-*.svg`: product-level composition diagram. A Chat Agent can be an existing service through a compatible API/adapter or the configured answer model.
- `*@2x.png`: high-resolution raster exports of the SVGs, created with the baoyu-diagram renderer.
- `voice-workspace-*.png`: current local application with the published Samantha role, bundled motion preview and right-side role selector. Uses the deterministic text-socket fixture; no live voice session or paid provider result is depicted.
- `avatar-controls-*.png`: the same Samantha preview with the native bottom presentation/material panel open. The two panels are captured separately to match the application's actual behavior.
- `knowledge-workspace-*.png`: current knowledge page with fictional Starflow/星河 documents and a deterministic retrieval fixture. These are UI examples, not a retrieval-quality benchmark.

Capture context: Chrome, 1440×900, English and Chinese UI; left application navigation collapsed, its reveal controls hidden for presentation. Test storage is isolated from user data; published role/avatar catalog copies seed the preview, and development tooling badges are hidden. No private conversation, provider key or account information is included. The README screenshots do not establish English voice acceptance.

The SVGs use system font fallbacks and have no remote fonts, scripts or image dependencies. They can be edited without regenerating bitmap artwork. Runtime and third-party asset terms remain as described in the repository's license and notices.
