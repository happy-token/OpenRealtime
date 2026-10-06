import type { AvatarAudioChunk, AvatarAudioSink } from "./avatar-output";
import type { BrowserAudioOutput } from "./browser-output";

/** Routes output and owns cancellation across browser and avatar renderers. */
export class PlaybackOutputController {
  private readonly cancelled = new Set<number>();

  constructor(
    private readonly browser: Pick<BrowserAudioOutput, "play" | "cancelGeneration" | "reset" | "setVolume">,
    private readonly avatar: () => AvatarAudioSink | null,
  ) {}

  enqueue(chunk: AvatarAudioChunk): boolean {
    if (this.cancelled.has(chunk.generation)) return false;
    const renderedByAvatar = this.avatar()?.enqueue(chunk) ?? false;
    if (!renderedByAvatar) this.playBrowser(chunk);
    return renderedByAvatar;
  }

  playBrowser(chunk: Parameters<BrowserAudioOutput["play"]>[0]): void {
    if (!this.cancelled.has(chunk.generation)) this.browser.play(chunk);
  }

  completeGeneration(generation: number): boolean {
    return !this.cancelled.has(generation)
      && (this.avatar()?.completeGeneration(generation) ?? false);
  }

  cancelGeneration(generation: number): ReturnType<BrowserAudioOutput["cancelGeneration"]> {
    this.cancelled.add(generation);
    const progress = this.browser.cancelGeneration(generation);
    this.avatar()?.cancelGeneration(generation);
    return progress;
  }

  reset(): void {
    this.browser.reset();
    this.avatar()?.reset();
    this.cancelled.clear();
  }

  setVolume(volume: number): void {
    this.browser.setVolume(volume);
    this.avatar()?.setVolume(volume);
  }
}
