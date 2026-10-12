# Build a voice guide and Q&A assistant with product documentation

This guide takes you from a short product document to a role that can answer questions about it using configured voice services. Start with voice; add an avatar later.

## Before you begin

- Use an account that can manage personal roles and documents, or [run the app locally](LOCAL-DEVELOPMENT.md). The public demo's access and quotas are operator-configured.
- Configure a compatible answer model, knowledge retrieval tool path, speech recognition and speech synthesis. [Cloud services](CLOUD-SERVICES.md)
- Allow microphone access on localhost or HTTPS. Credential-free demo replies do not validate real knowledge answers. English voice configurations and complete English conversation acceptance remain roadmap work; validate your selected combination.

## 1. Prepare a short document

Use this fictional sample first, or start with a small product FAQ. Include the product name, conditions and document version.

```text
Document name: Starflow product guide v1

Starflow is a project collaboration tool for small teams.
Starflow features: task boards, project documents and team collaboration.
Starflow trial period: 14 days.
Starflow trial team size: up to 5 people per team.
Starflow export: choose "Export Markdown" in project settings.
Starflow support hours: weekdays, 09:00–18:00.
This document does not specify pricing, refunds or mobile support.
```

Open Resource library → Knowledge library, add a resource, paste the text and create it. You can also import text-based PDF, DOCX, Markdown or TXT files. Scanned PDFs have no OCR support. Each extracted document is limited to 32,000 UTF-8 bytes; split longer documents by topic. [Import details, Chinese](../KNOWLEDGE-BASE-GUIDE.md)

## 2. Test retrieval first

Select the document, expand retrieval testing and search for "Starflow trial period" and "Starflow export". Inspect the excerpts for 14 days and Export Markdown.

Retrieval testing returns source excerpts, not a generated answer. If nothing matches, check the imported text and selection, then use words from the source. Default retrieval uses keyword-matched excerpts; paraphrases and complex conditions need separate testing.

## 3. Configure a role and bind the document

Create a personal role or open an editable role. Name it "Starflow product assistant", then:

1. Choose a voice supported by your configured speech service.
2. Select the product document in the role's knowledge settings and confirm saving succeeds.
3. Check tools and permissions so the selected model/session path can use knowledge retrieval. Importing or selecting a document does not prove the actual conversation retrieved it.
4. Add these instructions to the persona.

```text
You are the Starflow product assistant. Explain the product concisely.
Before answering questions about features, trials or usage rules,
search the bound knowledge library.
Preserve the source's conditions and limits. Answer the current question
first and expand when asked.
If the document does not cover a question, say so instead of inventing an answer.
When the user corrects a question, check the document for the updated question.
```

Instructions guide the model; test its actual behavior. Role overrides, service defaults and personal credentials have separate scopes. [Role configuration, Chinese](../guides/ROLE-CONFIGURATION.md)

## 4. Talk and check answers

Start a voice conversation with this role and allow microphone access.

| Try asking | Check for |
| --- | --- |
| Search the document and introduce Starflow | Small teams; task boards, project documents and collaboration |
| How long is the Starflow trial? | 14 days |
| How many people can use the Starflow trial? | Up to 5 people per team |
| How do I export from Starflow? | Export Markdown in project settings |
| What does Starflow cost? | The document does not specify a price |
| Say "stop" during an explanation, then ask about exports | The old response stops and the next question is answered |

Also test your own phrasing, pauses, short replies and corrections. These are acceptance targets, not results of a completed provider test. Successful retrieval, correct text answers and a working voice conversation are separate checks.

If an answer is wrong, inspect retrieved excerpts, role binding and tool calls before checking the answer model and service health. Record your language, models and version. [Knowledge troubleshooting, Chinese](../KNOWLEDGE-BASE-GUIDE.md)

## 5. Replace the sample with your product material

Import current product descriptions and FAQs. Check facts, conditions, exceptions and unanswered questions. After updating a document, test retrieval again and start a new conversation to avoid stale material from an earlier exchange.

Knowledge supplies reference text; long-term memory stores information scoped to a user and role; conversation history supports review and continuation. [Memory and history, Chinese](../MEMORY-AND-HISTORY-GUIDE.md)

## Optional: add an avatar

After voice Q&A works, select cloud rendering, local lip sync or prerecorded motion. Cloud avatars need separate credentials and authorization. Local synthesis has compute requirements; prerecorded motion does not match every spoken phoneme. Check video, audio and interruption behavior. [Avatar routes, Chinese](../DIGITAL-HUMAN-DRIVING.md)

Before sharing your deployment, configure authentication, persistence, credentials and quotas. [Deployment guide, Chinese](../deployment/public-trial.md)
