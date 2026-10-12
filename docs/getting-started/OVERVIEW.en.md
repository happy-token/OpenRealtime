# Meet OpenRealtime

**An open-source, customizable, interruptible voice AI agent product. Connect your Agent to chat and work through voice.**

Speak directly, ask follow-ups, add a requirement or correct a question during an answer. Choose voices, TTS, LLM, personas and tools to make the assistant your own. Add an avatar when visual presentation helps.

**[Try real-time voice](https://realtime.happy-token.cn/conversation?role_mode=conversation&experience=voice)** · [Quick guide, Chinese](../QUICK-START.md) · [Customize a role, Chinese](../guides/ROLE-CONFIGURATION.md) · [Connect your Agent](../guides/CHAT-AGENT-INTEGRATION.en.md)

## What you can do

- **Real-time voice interaction.** Speak directly, ask follow-ups and interrupt an answer to add a detail or make a correction. Let your Agent follow your conversation.
- **Connect your Agent.** Add speech input and output through a compatible API or adapter, keeping your models and business logic.
- **Chat and work through voice.** Have a conversation, consult documents, discuss a problem or use connected tools to help with work. Say what you need, then refine and confirm it as you talk.

Product guides, document Q&A and interactive characters can build on these capabilities. [Product documentation Q&A walkthrough](PRODUCT-ASSISTANT.en.md)

## Key features

### Your services. Your voice Agent.

Choose TTS, LLM and speech recognition services, then combine voices, personas and tools to customize how your assistant speaks and what it can do. Your existing Chat Agent can continue to supply the answers. [Role configuration, Chinese](../guides/ROLE-CONFIGURATION.md) · [Agent integration](../guides/CHAT-AGENT-INTEGRATION.en.md)

### Smart turn detection. Room to think.

Combine meaning and speaking activity to decide when your turn is complete. Reduce premature replies during thoughtful pauses and let the assistant respond at the right moment. Choose turn-decision services independently. [Turn detection](../SEMANTIC-EOT.md)

### Smart interruptions. Intent matters.

Distinguish an interruption from a brief acknowledgment and reduce false interruptions caused by background noise. When you stop an answer, make a correction or ask a new question, stop the old reply and respond to new input. Results depend on language, services and the actual environment. [Interruption handling](../SEMANTIC-INTERRUPTION.md)

## Make it your own

| Your goal | Your choices |
| --- | --- |
| A voice and style you like | TTS, voice, persona and response style |
| A service combination that fits | Speech recognition, LLM, speech synthesis and turn decisions |
| Keep an existing Agent's capabilities | Compatible text-chat APIs or a custom adapter |
| An assistant that knows your business | Your documents, retrieval and selected tools |
| Ongoing conversations | Long-term memory, history and continuation |
| A visible character | Optional cloud avatars, local lip sync or existing motion and talking materials |

Select recognition, answers and speech independently to combine economical services. Suitable combinations can cost less than GPT-Realtime-style end-to-end services; cloud APIs avoid self-hosted model GPUs. [Cost and service choices](../product/COST-AND-FLEXIBILITY.en.md)

## How it works

You speak; OpenRealtime recognizes the input and coordinates the turn. An answer model or your Chat Agent generates a reply, which a speech service reads aloud. Knowledge, tools and memory participate as configured; an avatar adds optional visual presentation.

Compatible text-chat APIs can reuse the existing client; custom services connect through an adapter. Keep your business logic and adjust voices, models and interaction decisions independently. [Integration paths](../guides/CHAT-AGENT-INTEGRATION.en.md)

## Choose a starting point

| Goal | Guide |
| --- | --- |
| Try a voice conversation | [Start talking](https://realtime.happy-token.cn/conversation?role_mode=conversation&experience=voice) · [Quick guide, Chinese](../QUICK-START.md) |
| Customize roles, voices and services | [Roles, Chinese](../guides/ROLE-CONFIGURATION.md) · [Cloud services](CLOUD-SERVICES.md) |
| Connect your Chat Agent | [Integration guide](../guides/CHAT-AGENT-INTEGRATION.en.md) |
| Answer questions from product documentation | [Hands-on walkthrough](PRODUCT-ASSISTANT.en.md) |
| Run in your own environment | [Local development](LOCAL-DEVELOPMENT.md) · [Deployment, Chinese](../deployment/public-trial.md) |
| Add an avatar | [Avatar guide, Chinese](../DIGITAL-HUMAN-DRIVING.md) |

The [public demo](https://realtime.happy-token.cn) has operator-configured roles, access and quotas. A self-hosted app uses your own services and data.

## Current scope

Default knowledge retrieval uses text and keyword-matched excerpts. Importing a document does not train the model, guarantee retrieval on every turn or guarantee correct answers. Check facts, conditions and questions outside your material. [Knowledge guide, Chinese](../KNOWLEDGE-BASE-GUIDE.md)

Without provider credentials, the local backend uses deterministic demo adapters to check the interface and application path. Real knowledge answers and cloud speech need compatible services. [Service setup](CLOUD-SERVICES.md)

Existing Chat Agent text interfaces can connect through compatible APIs or adapters. Unified onboarding and complete voice task collaboration for coding/action Agent backends remain TODO. English speech configuration and full conversation acceptance also need further work. [Support and scope](../reference/SUPPORT-AND-SCOPE.md) · [Roadmap](../../ROADMAP.md)
