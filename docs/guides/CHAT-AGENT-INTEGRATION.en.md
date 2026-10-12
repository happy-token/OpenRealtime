# Give your Chat Agent a voice

**Keep your conversational capabilities. Let users speak, follow up and interrupt.**

Connect an existing text-chat product through a compatible API or adapter. OpenRealtime turns speech into text for your Agent, speaks the returned content and optionally presents an avatar. Your Agent continues to supply your answer logic.

## Choose an integration path

| Existing service | Path | What to adapt |
| --- | --- | --- |
| OpenAI-compatible Chat Completions or Responses | Existing compatible model client | Endpoint, authentication, model name, stream events and cancellation |
| Custom HTTP, SDK or other text API | A conversation client adapter | Inputs, text/stream output, errors and cancellation |
| Coding or action Agent | Existing ACP, Codex, Claude or Hermes adapter foundations | Installation, permissions and task workflow; unified onboarding still needs work |

## Local compatible-API configuration

The local default answer path can use your own endpoint through `.env.local`:

```dotenv
VOICEAGENT_LLM_API_KEY=your-chat-agent-key
VOICEAGENT_LLM_BASE_URL=https://your-chat-agent.example.com/v1
VOICEAGENT_LLM_MODEL=your-agent-model
VOICEAGENT_LLM_API_STYLE=chat_completions
```

Your service must implement the selected protocol and model identifier. For a Responses-compatible service, use `responses`. Role provider overrides, public admission bindings and tool-aware answer paths have separate configuration scopes; changing defaults does not configure every path.

## Custom adapter boundaries

- [LlmClient](../../server/brain/llm_clients.py) returns text from `complete(system_prompt, user_text)`.
- Implement `stream` for incremental text; [ChatBrain](../../server/brain/chat_brain.py) consumes it.
- Tool-aware responses use the separate `ToolCallingLlmClient` contract. Plain text compatibility does not imply tool-call compatibility.
- Your adapter handles authentication, session association, timeouts and cancellation, with separate user contexts.

Start with the [compatible client](../../server/brain/plugins/openai_compatible_llm_client.py) and [pipeline interfaces](../VOICE-PIPELINE.md). Custom adapters require development and assembly; a generic one-click UI for arbitrary Chat Agents is not provided.

## Check the experience

Verify replies, streaming speech, follow-ups, stops, corrections, timeouts and reconnects. Knowledge, tools and memory can come from your Agent or be combined with OpenRealtime's features; define their data and permission boundaries.

Stopping speech and cancelling background work are separate operations. Connecting a text-chat interface does not establish complete onboarding, progress reporting and task collaboration for coding/action Agents. Validate each backend's capabilities separately.

[Service setup](../getting-started/CLOUD-SERVICES.md) · [Role settings, Chinese](ROLE-CONFIGURATION.md) · [Architecture](../ARCHITECTURE.md)
