# Local GPT Voice evidence inventory

This directory records the Voice-specific evidence found in the locally
installed Codex desktop app. It is an inventory, not a redistribution of the
application's proprietary bundles.

## Files

- `evidence.json`: app identity, build hashes, relevant extracted asset paths,
  and the files in which each protocol identifier occurs.
- `protocol-catalog.json`: normalized media, app-server, Sideband, Voice tool,
  startup barrier, routing mode, and correlation-ID catalog used by the
  reference framework and diagrams.
- `../../scripts/extract_gpt_voice_evidence.py`: reproducible extractor.

## Rebuild

The basic inventory needs only the installed application:

```bash
.venv/bin/python scripts/extract_gpt_voice_evidence.py
```

To identify Voice assets inside `app.asar`, extract the archive into a
temporary directory using an ASAR-compatible tool, then run:

```bash
.venv/bin/python scripts/extract_gpt_voice_evidence.py \
  --extracted-asar /path/to/extracted/app-asar \
  --output research/gpt-voice-local/evidence.json
```

The generated hashes intentionally pin conclusions to one inspected app
build. Re-run the extractor after upgrading the desktop app.

## Evidence boundary

Directly observable locally:

- microphone capture, AudioWorklet startup buffering, WebRTC, and the
  `oai-events` DataChannel;
- `thread/realtime/*` app-server methods and notifications;
- sideband-related protocol strings in the Codex backend;
- dynamic tool calls, thread delegation, result injection, and Voice tools.

Not available locally:

- the cloud Realtime model implementation;
- server-side routing, scheduling, and model weights;
- the complete consumer ChatGPT Voice implementation.
