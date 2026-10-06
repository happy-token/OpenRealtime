import type { AvatarAudioChunk, AvatarAudioSink } from "./avatar-output";
import type { BrowserAudioOutput } from "./browser-output";
import type { OutputStopResult, OutputStopTarget, SentencePlaybackPermit } from "../protocol/v2";

/** Routes output and owns cancellation across browser and avatar renderers. */
export class PlaybackOutputController {
  private readonly cancelled = new Set<number>();
  private outputEpoch: string | null = null;
  private readonly cancelledSpeech = new Set<string>();
  private readonly routes = new Map<string, { generation: number; avatar: boolean }>();
  private readonly latestSpeech = new Map<number, string>();
  private readonly stopReceipts = new Map<string, OutputStopResult>();
  private readonly sentenceModes = new Map<string, string>();
  private readonly pendingStops = new Map<string, { target: OutputStopTarget; mode: string; promise: Promise<OutputStopResult> }>();
  private highestGeneration = -1;
  private outputBlocked = false;

  constructor(
    private readonly browser: Pick<BrowserAudioOutput, "play" | "canPlay" | "stopOutput" | "stopAtSentenceEnd" | "cancelGeneration" | "reset" | "setVolume">,
    private readonly avatar: () => AvatarAudioSink | null,
  ) {}

  enqueue(chunk: AvatarAudioChunk): boolean {
    if (!this.canEnqueue(chunk)) return false;
    const renderedByAvatar = this.avatar()?.enqueue(chunk) ?? false;
    if (renderedByAvatar) this.recordRoute(chunk, true);
    else this.playBrowser(chunk);
    return renderedByAvatar;
  }

  playBrowser(chunk: Parameters<BrowserAudioOutput["play"]>[0]): void {
    if (this.canEnqueue(chunk) && this.browser.play(chunk)) this.recordRoute(chunk, false);
  }

  beginEpoch(outputEpoch: string): void {
    if (!outputEpoch) throw new Error("output epoch must be non-empty");
    this.reset();
    this.outputEpoch = outputEpoch;
  }

  canEnqueue(chunk: { generation: number; speechId: string }): boolean {
    if (this.outputBlocked || this.pendingStops.size > 0 || this.cancelled.has(chunk.generation)
      || this.cancelledSpeech.has(chunk.speechId) || chunk.generation < this.highestGeneration) return false;
    const route = this.routes.get(chunk.speechId);
    if (route && (route.generation !== chunk.generation || this.latestSpeech.get(chunk.generation) !== chunk.speechId)) return false;
    return this.browser.canPlay(chunk);
  }

  canUpdateResponse(): boolean {
    return !this.outputBlocked && this.pendingStops.size === 0;
  }

  isCurrentSpeech(generation: number, speechId: string): boolean {
    return generation === this.highestGeneration && this.latestSpeech.get(generation) === speechId;
  }

  stopOutput(request: OutputStopTarget): OutputStopResult {
    const target: OutputStopTarget = { output_epoch: request.output_epoch, speech_id: request.speech_id,
      generation: request.generation, stop_command_id: request.stop_command_id };
    const result = (outcome: OutputStopResult["outcome"]): OutputStopResult => ({ ...target,
      type: "output_stop_result", outcome, played_position_samples: null });
    if (target.output_epoch !== this.outputEpoch) return result("stale");
    if (this.pendingStops.has(target.stop_command_id) || this.sentenceModes.has(target.stop_command_id)) {
      this.blockOutput();
      throw new Error("stop operation identity was reused with another mode");
    }
    const previous = this.stopReceipts.get(target.stop_command_id);
    if (previous) {
      if (previous.output_epoch !== target.output_epoch || previous.speech_id !== target.speech_id
        || previous.generation !== target.generation) {
        this.blockOutput();
        throw new Error("stop operation identity was reused");
      }
      return previous;
    }
    if (this.stopReceipts.size + this.pendingStops.size >= 512) {
      this.blockOutput();
      return result("unknown");
    }
    const route = this.routes.get(target.speech_id);
    if (route && route.generation !== target.generation) {
      const receipt = result("stale");
      this.stopReceipts.set(target.stop_command_id, receipt);
      return receipt;
    }
    this.cancelledSpeech.add(target.speech_id);
    let receipt: OutputStopResult;
    try {
      receipt = this.browser.stopOutput(target);
      if (route?.avatar) {
        // These sinks expose a command submission, not a stop acknowledgement.
        if (this.isCurrentSpeech(target.generation, target.speech_id)) this.avatar()?.cancelGeneration(target.generation);
        receipt = result("unknown");
      }
    } catch {
      receipt = result("unknown");
    }
    if (receipt.outcome === "unknown") {
      this.blockOutput();
    }
    this.stopReceipts.set(target.stop_command_id, receipt);
    return receipt;
  }

  stopAtSentenceEnd(request: OutputStopTarget, permit: SentencePlaybackPermit): Promise<OutputStopResult> {
    const target = { output_epoch: request.output_epoch, speech_id: request.speech_id,
      generation: request.generation, stop_command_id: request.stop_command_id };
    if (target.output_epoch !== this.outputEpoch) return Promise.resolve({ ...target,
      type: "output_stop_result", outcome: "stale", played_position_samples: null });
    const mode = JSON.stringify([permit.permit_id, permit.input_id, permit.input_version,
      permit.response_id, permit.reply_version, permit.sentence_id, permit.audio_start_samples,
      permit.audio_end_samples, permit.sample_rate_hz, permit.max_wait_ms]);
    const pending = this.pendingStops.get(target.stop_command_id);
    const previous = this.stopReceipts.get(target.stop_command_id);
    const original = pending?.target ?? previous;
    if (original) {
      if (original.output_epoch !== target.output_epoch || original.speech_id !== target.speech_id
        || original.generation !== target.generation
        || (pending?.mode ?? this.sentenceModes.get(target.stop_command_id)) !== mode) {
        this.blockOutput();
        throw new Error("stop operation identity was reused");
      }
      return pending?.promise ?? Promise.resolve(previous as OutputStopResult);
    }
    const route = this.routes.get(target.speech_id);
    if (route?.avatar || route?.generation !== target.generation
      || this.stopReceipts.size + this.pendingStops.size >= 512) {
      // A void avatar cancel cannot certify a retained sentence or its end.
      const receipt = this.stopOutput(target);
      if (this.stopReceipts.has(target.stop_command_id)) this.sentenceModes.set(target.stop_command_id, mode);
      return Promise.resolve(receipt);
    }
    this.cancelledSpeech.add(target.speech_id);
    let settle!: (receipt: OutputStopResult) => void;
    const operation = { target, mode, promise: new Promise<OutputStopResult>(resolve => { settle = resolve; }) };
    // Install ownership before invoking a renderer that can complete immediately.
    this.pendingStops.set(target.stop_command_id, operation);
    void (async () => {
      let receipt: OutputStopResult;
      try { receipt = await this.browser.stopAtSentenceEnd(target, { ...permit }); }
      catch { receipt = { ...target, type: "output_stop_result", outcome: "unknown", played_position_samples: null }; }
      // Physical uncertainty survives attachment/reset ownership changes.
      if (receipt.outcome === "unknown") this.blockOutput();
      if (this.pendingStops.get(target.stop_command_id) === operation) {
        this.pendingStops.delete(target.stop_command_id);
        this.stopReceipts.set(target.stop_command_id, receipt);
        this.sentenceModes.set(target.stop_command_id, mode);
      }
      settle(receipt);
    })();
    return operation.promise;
  }

  private blockOutput(): void {
    this.outputBlocked = true;
    this.browser.setVolume(0);
    this.avatar()?.setVolume(0);
  }

  private recordRoute(chunk: { generation: number; speechId: string }, avatar: boolean): void {
    this.routes.set(chunk.speechId, { generation: chunk.generation, avatar });
    this.latestSpeech.set(chunk.generation, chunk.speechId);
    this.highestGeneration = Math.max(this.highestGeneration, chunk.generation);
  }

  completeGeneration(generation: number): boolean {
    const speechId = this.latestSpeech.get(generation);
    return !this.outputBlocked && this.pendingStops.size === 0 && !this.cancelled.has(generation)
      && (!speechId || !this.cancelledSpeech.has(speechId))
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
    this.outputEpoch = null;
    this.cancelledSpeech.clear();
    this.routes.clear();
    this.latestSpeech.clear();
    this.stopReceipts.clear();
    this.sentenceModes.clear();
    this.pendingStops.clear();
    this.highestGeneration = -1;
    // A void renderer reset cannot prove a previously unknown stop completed.
    // Only construction of a new output controller clears this failure latch.
    if (this.outputBlocked) this.avatar()?.setVolume(0);
  }

  setVolume(volume: number): void {
    const allowedVolume = this.outputBlocked ? 0 : volume;
    this.browser.setVolume(allowedVolume);
    this.avatar()?.setVolume(allowedVolume);
  }
}
