import type { TranscriptEntry } from "@/hooks/use-voice-session";
import { Transcript } from "./transcript";

interface ChatViewProps {
  entries: TranscriptEntry[];
  active?: boolean;
}

export function ChatView({ entries, active = true }: ChatViewProps) {
  return (
    <section className="view chat-view">
      <Transcript entries={entries} active={active} />
    </section>
  );
}
