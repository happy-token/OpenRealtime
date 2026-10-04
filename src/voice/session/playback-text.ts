import type { AssistantTextAlignmentFrame } from "@/lib/frames";

/** Provider text cues advance only on the device playback timeline. */
export class PlaybackTextTimeline {
  private generation = -1;
  private speechId: string | null = null;
  private positionUs = 0;
  private cues: AssistantTextAlignmentFrame[] = [];
  private settled = false;

  private select(generation: number, speechId: string): boolean {
    if (generation < this.generation) return false;
    if (generation > this.generation) {
      this.generation = generation;
      this.speechId = speechId;
      this.positionUs = 0;
      this.cues = [];
      this.settled = false;
    }
    return !this.settled && this.speechId === speechId;
  }

  add(cue: AssistantTextAlignmentFrame): string | null {
    if (!this.select(cue.generation, cue.speech_id)) return null;
    if (!this.cues.some(item => item.audio_start_us === cue.audio_start_us && item.text === cue.text)) {
      this.cues.push(cue);
      this.cues.sort((a, b) => a.audio_start_us - b.audio_start_us || a.audio_end_us - b.audio_end_us);
    }
    return this.visibleText();
  }

  advance(generation: number, speechId: string, positionUs: number): string | null {
    if (!Number.isFinite(positionUs) || positionUs < 0 || !this.select(generation, speechId)) return null;
    this.positionUs = Math.max(this.positionUs, positionUs);
    return this.visibleText();
  }

  private visibleText(completedOnly = false): string {
    // Small guard prevents queued text from appearing before the first samples.
    return this.cues.filter(cue => (completedOnly ? cue.audio_end_us : cue.audio_start_us + 20_000) <= this.positionUs)
      .reduce((text, cue) => cue.text.length > text.length ? cue.text : text, "");
  }

  stop(generation: number): string | null {
    if (generation !== this.generation || this.settled) return null;
    const text = this.visibleText(true);
    this.settled = true;
    return text;
  }

  finish(generation: number, fullText: string): string | null {
    if (generation < this.generation || (generation === this.generation && this.settled)) return null;
    this.generation = generation;
    this.settled = true;
    return fullText;
  }

  reset(): void {
    this.generation = -1;
    this.speechId = null;
    this.positionUs = 0;
    this.cues = [];
    this.settled = false;
  }
}
