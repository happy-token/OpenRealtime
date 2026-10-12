# Connect cloud services

[Local startup](LOCAL-DEVELOPMENT.md) · [Documentation index](../README.md)

The cloud route uses hosted inference and avatar services, so it does not require self-hosted model GPUs. It still requires the application backend, service credentials and paid usage where applicable.

For your first product guide and Q&A assistant, configure speech recognition, an answer model with knowledge-tool support, and speech synthesis first. Check the [document-to-voice walkthrough](PRODUCT-ASSISTANT.en.md) before adding an optional avatar service.

## Minimal local voice configuration

The current default direct speech route uses Doubao for ASR/TTS and can use DeepSeek for answers. For a local configuration, put your own keys in `.env.local`:

```dotenv
DEEPSEEK_API_KEY=your-deepseek-key
DOUBAO_API_KEY=your-doubao-speech-key
VOICEAGENT_ASR_BACKEND=doubao-direct
VOICEAGENT_TTS_BACKEND=doubao-direct
VOICEAGENT_DEMO_TOOLS=1
OPENREALTIME_AVATAR_RENDERER_MODE=disabled
```

`VOICEAGENT_DEMO_TOOLS=1` enables the local tool/knowledge path when no public admission binding is present. Select knowledge in the role and check its tool permissions; the flag does not bypass authorization or guarantee that a model retrieves on every turn. Public deployments use their separate admission and account configuration.

Use a speech key authorized for the selected ASR and TTS resources, and account for service usage fees. Restart `pnpm dev`, then verify transcription, source retrieval and a spoken answer. If your role overrides a provider, configure that provider as well or clear the override to use the defaults. See [provider details](../reference/WEB-DEMO-CONFIGURATION.md) for other supported routes and speech resource settings.

This is a repository-backed configuration example, not a fresh account or English voice acceptance result. Keep actual keys local; optional avatar keys are unnecessary for this voice-only path.

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
