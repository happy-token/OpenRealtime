import { markdownToSpeechText } from "@/lib/message-text";

export function shouldResetTranscriptForSession(
  previousSessionId: string | null,
  nextSessionId: string | null,
  continuationFromSessionId: string | null = null,
): boolean {
  return (
    previousSessionId !== null &&
    nextSessionId !== null &&
    previousSessionId !== nextSessionId &&
    previousSessionId !== continuationFromSessionId
  );
}

export interface TranscriptEntry {
  role: "user" | "assistant";
  text: string;
  generation?: number;
  turnId?: string;
  revision?: number;
  isFinal?: boolean;
  status?: AssistantMessageStatus;
}

export type AssistantMessageStatus = "streaming" | "completed" | "interrupted" | "failed";

export interface AssistantOutputText {
  generation: number | null;
  display: string;
  spoken: string;
}

export interface UserTranscriptUpdate {
  turnId?: string | null;
  revision?: number | null;
  isFinal?: boolean;
}

export function mergeAssistantTranscript(
  transcript: TranscriptEntry[],
  generation: number,
  text: string,
): TranscriptEntry[] {
  const existingIndex = transcript.findIndex(
    (entry) => entry.role === "assistant" && entry.generation === generation,
  );
  if (existingIndex >= 0) {
    return transcript.flatMap((entry, index) => {
      if (entry.role !== "assistant" || entry.generation !== generation) {
        return [entry];
      }
      return index === existingIndex ? [{ ...entry, text, status: "streaming" }] : [];
    });
  }
  return [...transcript, { role: "assistant", text, generation, status: "streaming" }];
}

export function settleAssistantTranscript(
  transcript: TranscriptEntry[],
  generation: number,
  status: Exclude<AssistantMessageStatus, "streaming">,
): TranscriptEntry[] {
  return transcript.map((entry) => (
    entry.role === "assistant" && entry.generation === generation
      ? { ...entry, status }
      : entry
  ));
}

export function updateAssistantOutputText(
  current: AssistantOutputText,
  kind: "display" | "spoken",
  generation: number,
  text: string,
): AssistantOutputText {
  const next = current.generation === generation
    ? current
    : { generation, display: "", spoken: "" };
  return { ...next, [kind]: text };
}

export function browserSpeechTextForResponse(
  output: AssistantOutputText,
  generation: number,
): string {
  if (output.generation !== generation) return "";
  return output.spoken.trim() || markdownToSpeechText(output.display);
}

export function mergeUserTranscript(
  transcript: TranscriptEntry[],
  generation: number,
  text: string,
  update: UserTranscriptUpdate = {},
): TranscriptEntry[] {
  const turnId = update.turnId ?? undefined;
  const existingIndex = transcript.findIndex(
    (entry) =>
      entry.role === "user"
      && (turnId ? entry.turnId === turnId : entry.generation === generation),
  );
  if (existingIndex >= 0) {
    const existing = transcript[existingIndex];
    if (
      update.revision != null
      && existing.revision != null
      && update.revision < existing.revision
    ) {
      return transcript;
    }
    return transcript.flatMap((entry, index) => {
      const sameTurn = entry.role === "user" && (
        turnId ? entry.turnId === turnId : entry.generation === generation
      );
      if (!sameTurn) return [entry];
      if (index !== existingIndex) return [];
      return [{
        ...entry,
        text,
        generation,
        ...(turnId ? { turnId } : {}),
        ...(update.revision == null ? {} : { revision: update.revision }),
        ...(update.isFinal === undefined ? {} : { isFinal: update.isFinal }),
      }];
    });
  }
  const optimisticIndex = transcript.findLastIndex(
    (entry) =>
      entry.role === "user"
      && entry.generation === undefined
      && entry.text === text,
  );
  if (optimisticIndex >= 0) {
    return transcript.map((entry, index) => (
      index === optimisticIndex
        ? {
            ...entry,
            text,
            generation,
            ...(turnId ? { turnId } : {}),
            ...(update.revision == null ? {} : { revision: update.revision }),
            ...(update.isFinal === undefined ? {} : { isFinal: update.isFinal }),
          }
        : entry
    ));
  }
  return [
    ...transcript,
    {
      role: "user",
      text,
      generation,
      ...(turnId ? { turnId } : {}),
      ...(update.revision == null ? {} : { revision: update.revision }),
      ...(update.isFinal === undefined ? {} : { isFinal: update.isFinal }),
    },
  ];
}

export interface AssistantCaptionState {
  text: string;
  spokenGeneration: number | null;
}

export interface AssistantCaptionUpdate {
  kind: "display" | "spoken";
  generation: number;
  text: string;
}

export function updateAssistantCaption(
  current: AssistantCaptionState,
  update: AssistantCaptionUpdate,
): AssistantCaptionState {
  if (update.kind === "spoken") {
    return { text: update.text, spokenGeneration: update.generation };
  }
  if (current.spokenGeneration === update.generation) return current;
  return { ...current, text: update.text };
}
