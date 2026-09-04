---
status: accepted
---

# Multi-representation conversation content and explicit speech delivery

One Assistant Conversation Item may carry related Semantic Content, Display Content, and Spoken Content without becoming three conversational turns. Semantic Content preserves complete structured meaning, Display Content is the rich UI projection, and Spoken Content is the text intentionally sent for voice delivery. A separate Delivery Record captures what was actually played, including playback position, interruption, precision, and Delivered Speech Transcript. Generated or sent audio is never treated as delivered; the playback endpoint reports progress explicitly.

ADR-0071 places that endpoint behavior behind Device Audio Output Runtime. WebSocket playback and future RTC remote-track playback must emit the same correlated progress and honor the same generation-aware clear semantics; neither transport buffering nor local decoding changes Delivery Record meaning.

External speech uses an explicit `StartSpeech -> AppendSpeechText* -> CommitSpeech | CancelSpeech` lifecycle correlated by `speech_id` and text sequence. Its Speech Context Policy is `AUTO` by default, `APPEND`, or `NONE`: `AUTO` attaches speech to a source item or creates an assistant item when no source exists. Interrupted Context Policy defaults to `DELIVERED_ONLY`, with `FULL_WITH_DELIVERY_STATE` and `OMIT` as explicit alternatives. Streaming text is checkpointed in a Speech Draft and settles into Conversation Item content plus a Delivery Record on completion, cancellation, failure, or recovery. TTS only synthesizes Spoken Content; a replaceable Speech Renderer derives speech from Semantic/Display Content when needed.

We rejected using one `TextDelta` for display, history, and TTS because rich Agent results and concise speech intentionally differ. We also rejected equating provider output transcripts or server sends with user delivery because interruption and client buffering make that factually wrong.
