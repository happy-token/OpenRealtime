# Lower costs and more flexibility

Reviewed: 2026-10-12.

OpenRealtime lets you choose listening, answering, speaking and turn decisions separately. Combine economical speech services with a text model or your existing Chat Agent, then change the combination as your needs evolve. **Suitable combinations can provide lower voice costs than GPT-Realtime-style end-to-end services.**

## Where savings can come from

- Choose speech recognition, answer generation and speech synthesis separately for your budget and experience.
- Reuse an existing Chat Agent through an adapter instead of moving its answer logic into a speech model.
- Start with cloud APIs without self-hosted model GPUs; add avatars only when useful.
- Adjust the model, voice and interaction decisions independently.

## Compare total costs

```text
OpenRealtime combination
= ASR + answer model/Chat Agent + TTS + turn decisions
  + tools/retrieval + application hosting + optional avatar

End-to-end service
= audio/text/image model usage + tools/retrieval
  + application hosting + optional avatar
```

Speech duration, history, cache usage, interruptions and retries affect the result. Compare the same task and target quality, recording models, language, network and usage.

## What current price sheets establish

[OpenAI pricing](https://developers.openai.com/api/docs/pricing) lists GPT-Realtime-2.1 audio input/output at $32/$64 per million tokens and its mini variant at $10/$20. The [Realtime billing guide](https://developers.openai.com/api/docs/guides/voice-latency-cost) explains how history, caching and input transcription affect charges.

[DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/) lists Flash uncached text input/output at $0.30/$1.20 per million tokens during peak hours and $0.15/$0.60 off-peak. These are text-model choices, not a complete voice-service bill. Dividing text-token prices by audio-token prices does not establish a total savings ratio.

Check speech services against your selected ASR/TTS products, voices and plans, including [Doubao's official billing](https://www.volcengine.com/docs/6561/1359370). Its full current price sheet was not verified in this review, so no speech rate is quoted here. No new matched-task billing experiment was run.

The product advantage is the ability to lower costs through economical components and control each layer. A fixed savings percentage, universal cost advantage or equal speech quality needs a specific configuration and matched comparison.

## What flexibility gives you

Keep your answer logic and business material while changing voice or interaction strategy. Start with voice, then add an avatar. Native end-to-end services also support tools and interaction; include voice quality, latency and maintenance in your choice.

[Service setup](../getting-started/CLOUD-SERVICES.md) · [Chat Agent integration](../guides/CHAT-AGENT-INTEGRATION.en.md) · [Evidence](CLAIMS-AND-EVIDENCE.md)
