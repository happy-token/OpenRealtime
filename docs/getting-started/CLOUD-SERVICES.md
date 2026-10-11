# Connect cloud services

[Local startup](LOCAL-DEVELOPMENT.md) · [Documentation index](../README.md)

The cloud route uses hosted inference and avatar services, so it does not require self-hosted model GPUs. It still requires the application backend, service credentials and paid usage where applicable.

## Configure a supported route

1. Review [`.env.example`](../../.env.example) and select supported ASR, answer-model and TTS providers. Do not copy credentials into documentation, screenshots or Git.
2. Store platform credentials in local environment files. The development scripts load `.env` followed by `.env.local`; explicitly exported settings can override values where the launcher supports them. Check the relevant script before diagnosing precedence.
3. Start/restart the application and verify the advertised speech capabilities, a real transcription and spoken response. An echo or browser fallback is not a provider acceptance test.
4. Select the role's voice/persona/tools/knowledge as needed. Role-level supplier overrides and platform defaults are distinct; individual provider keys have their own owner/scope.
5. For avatars, configure the selected cloud service separately and check readiness, first video frame, streamed audio and interruption behavior.

See [retained provider/console examples](../reference/WEB-DEMO-CONFIGURATION.md) and [deployment](../deployment/public-trial.md) for exact service-specific settings. Do not infer that every provider menu entry has a verified adapter or an English configuration.

## Decision provider

`VOICEAGENT_EOT_PROVIDER` and `VOICEAGENT_INTERRUPTION_PROVIDER` default to `llm` in the environment example. Jev is optional and can be configured independently for these decisions; check its credentials/dependencies and [decision contract](../SEMANTIC-DECISION-PLUGINS.md). It does not replace the answer model or the runtime's cancellation policy.

## Verify the selected combination

Record the app version, providers/models, language, browser and network. Test a request, pause, short response, backchannel, stop, correction and new task. For a cloud avatar also verify cancellation and mode-specific output. Compare user-end-of-speech to actual playback separately from classification-call time.

English ASR/TTS configuration and end-to-end English acceptance remain roadmap work until the selected combination is documented and tested. This guide adds documentation, not new adapters or a paid-service test result.
