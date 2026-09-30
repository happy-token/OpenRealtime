import type { AvatarAudioChunk, AvatarAudioSink } from "@/voice/audio/avatar-output";

type Fetcher = typeof fetch;

interface StreamingGeneration {
  sampleRateHz: number;
  source: Int16Array;
  sentSamples: number;
  sequence: number;
  final: boolean;
  started: boolean;
  controller: AbortController;
  request: Promise<void>;
  pollTimer: ReturnType<typeof setTimeout> | null;
  onStarted: () => void;
  onEnded: () => void;
  chunks: AvatarAudioChunk[];
}

interface VolumeTarget { volume: number }
const UPLOAD_SAMPLES = 4_800; // 300 ms, so a 320 ms source chunk can retain its resampling neighbour.

/** Streams one continuous PCM timeline per TTS generation to our renderer. */
export class LiveTalkingAudioBridge implements AvatarAudioSink {
  private baseUrl = "";
  private sessionId = "";
  private video: VolumeTarget | null = null;
  private volume = 0.8;
  private onFailure: ((error: Error) => void) | null = null;
  private readonly active = new Map<number, StreamingGeneration>();

  private readonly fetcher: Fetcher;

  constructor(fetcher: Fetcher = fetch) {
    // Native browser fetch must not receive the bridge object as its receiver.
    this.fetcher = (input, init) => fetcher(input, init);
  }

  connect(baseUrl: string, sessionId: string, video?: VolumeTarget, onFailure?: (error: Error) => void): void {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.sessionId = sessionId;
    this.video = video ?? null;
    this.onFailure = onFailure ?? null;
    if (this.video) this.video.volume = this.volume;
  }

  enqueue(chunk: AvatarAudioChunk): boolean {
    if (!this.baseUrl || !this.sessionId || !Number.isFinite(chunk.sampleRateHz) || chunk.sampleRateHz <= 0) return false;
    let current = this.active.get(chunk.generation);
    if (current && (current.sampleRateHz !== chunk.sampleRateHz || current.final)) return false;
    const incoming = decodePcm16Chunks([chunk.pcm16Base64]);
    if ((current?.source.length ?? 0) + incoming.length > chunk.sampleRateHz * 120) return false;
    if (!current) {
      current = {
        sampleRateHz: chunk.sampleRateHz, source: new Int16Array(0), sentSamples: 0,
        sequence: 0, final: false, started: false, controller: new AbortController(),
        request: Promise.resolve(), pollTimer: null, onStarted: chunk.onStarted, onEnded: chunk.onEnded, chunks: [],
      };
      this.active.set(chunk.generation, current);
    }
    const combined = new Int16Array(current.source.length + incoming.length);
    combined.set(current.source);
    combined.set(incoming, current.source.length);
    current.source = combined;
    current.chunks.push(chunk);
    current.onEnded = chunk.onEnded;
    // Keep resampling phase continuous; retain the last source sample until its
    // interpolation neighbour arrives, rather than rounding each HTTP chunk.
    const available = Math.max(0, Math.min(
      Math.ceil((combined.length - 1) * 16_000 / current.sampleRateHz),
      Math.round(combined.length * 16_000 / current.sampleRateHz),
    ));
    if (available - current.sentSamples >= UPLOAD_SAMPLES) this.flush(chunk.generation, current, available, false);
    return true;
  }

  completeGeneration(generation: number): boolean {
    const current = this.active.get(generation);
    if (!current || current.source.length === 0) return false;
    if (current.final) return true;
    current.final = true;
    this.flush(generation, current, Math.max(1, Math.round(current.source.length * 16_000 / current.sampleRateHz)), true);
    return true;
  }

  private flush(generation: number, current: StreamingGeneration, end: number, final: boolean): void {
    const pcm = resampleRange(current.source, current.sampleRateHz, current.sentSamples, end);
    current.sentSamples = end;
    const form = new FormData();
    if (pcm.length) form.append("file", new Blob([pcm16ToWav(pcm, 16_000)], { type: "audio/wav" }), `response-${generation}.wav`);
    form.append("sessionid", this.sessionId);
    form.append("generation", String(generation));
    form.append("sequence", String(current.sequence++));
    form.append("final", final ? "1" : "0");
    const endpoint = this.baseUrl;
    current.request = current.request.then(async () => {
      if (current.controller.signal.aborted) return;
      const response = await this.fetcher(`${endpoint}/humanaudio`, {
        method: "POST", body: form, signal: current.controller.signal,
      });
      const payload = await response.json() as { code?: number; msg?: string; discarded?: boolean };
      if (!response.ok || payload.code !== 0 || payload.discarded) throw new Error(payload.msg || "Avatar audio upload rejected");
      if (this.active.get(generation) !== current) return;
      if (current.pollTimer === null) this.schedulePoll(generation, current);
    }).catch((error: unknown) => {
      if (this.active.get(generation) !== current) return;
      console.error("Avatar streaming failed", error);
      this.fail(error instanceof Error ? error : new Error("Avatar streaming failed"));
    });
  }

  private schedulePoll(generation: number, current: StreamingGeneration): void {
    current.pollTimer = setTimeout(() => { void this.poll(generation, current); }, 120);
  }

  private async poll(generation: number, current: StreamingGeneration): Promise<void> {
    try {
      const query = new URLSearchParams({ sessionid: this.sessionId, generation: String(generation) });
      const response = await this.fetcher(`${this.baseUrl}/audio_status?${query}`, { signal: current.controller.signal });
      const status = await response.json() as { code?: number; state?: string };
      if (!response.ok || status.code !== 0) throw new Error("Avatar playback status unavailable");
      if (this.active.get(generation) !== current) return;
      if (!current.started && (status.state === "playing" || status.state === "completed")) {
        current.started = true;
        current.onStarted();
      }
      if (status.state === "completed" || status.state === "cancelled") {
        this.clearGeneration(generation);
        current.onEnded();
      } else {
        this.schedulePoll(generation, current);
      }
    } catch (error) {
      if (this.active.get(generation) !== current) return;
      console.error("Avatar playback failed", error);
      this.fail(error instanceof Error ? error : new Error("Avatar playback failed"));
    }
  }

  cancelGeneration(generation: number): void {
    this.clearGeneration(generation);
    if (!this.baseUrl || !this.sessionId) return;
    void this.fetcher(`${this.baseUrl}/interrupt_talk`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionid: this.sessionId, generation }),
    }).catch(() => undefined);
  }

  isActive(generation: number): boolean { return this.active.has(generation); }

  reset(): void {
    for (const generation of this.active.keys()) this.cancelGeneration(generation);
  }

  disconnect(): void {
    this.reset();
    this.baseUrl = "";
    this.sessionId = "";
    this.video = null;
    this.onFailure = null;
  }

  /** Stop the renderer before replaying buffered audio, so both outputs cannot overlap. */
  fail(error: Error): void {
    const pending = [...this.active.values()];
    const onFailure = this.onFailure;
    this.disconnect();
    onFailure?.(error);
    for (const current of pending) {
      if (current.chunks.every(chunk => chunk.onFallback)) {
        current.chunks.forEach((chunk, index) => chunk.onFallback?.(
          chunk.isFinal || (current.final && index === current.chunks.length - 1),
        ));
      } else {
        current.onEnded();
      }
    }
  }

  setVolume(volume: number): void {
    this.volume = Math.max(0, Math.min(1, volume));
    if (this.video) this.video.volume = this.volume;
  }

  private clearGeneration(generation: number): void {
    const current = this.active.get(generation);
    if (!current) return;
    current.controller.abort();
    if (current.pollTimer !== null) clearTimeout(current.pollTimer);
    this.active.delete(generation);
  }
}

function decodePcm16Chunks(chunks: string[]): Int16Array {
  const byteChunks = chunks.map((chunk) => Uint8Array.from(atob(chunk), (character) => character.charCodeAt(0)));
  const byteLength = byteChunks.reduce((total, chunk) => total + chunk.byteLength, 0);
  const bytes = new Uint8Array(byteLength - (byteLength % 2));
  let offset = 0;
  for (const chunk of byteChunks) {
    const slice = chunk.subarray(0, Math.min(chunk.byteLength, bytes.byteLength - offset));
    bytes.set(slice, offset);
    offset += slice.byteLength;
  }
  const view = new DataView(bytes.buffer);
  const samples = new Int16Array(bytes.byteLength / 2);
  for (let index = 0; index < samples.length; index += 1) samples[index] = view.getInt16(index * 2, true);
  return samples;
}

function resampleRange(input: Int16Array, sourceRate: number, start: number, end: number): Int16Array {
  const output = new Int16Array(end - start);
  const scale = sourceRate / 16_000;
  for (let index = start; index < end; index += 1) {
    const position = index * scale;
    const left = Math.min(input.length - 1, Math.floor(position));
    const right = Math.min(input.length - 1, left + 1);
    const weight = position - left;
    output[index - start] = Math.round(input[left]! * (1 - weight) + input[right]! * weight);
  }
  return output;
}

function pcm16ToWav(samples: Int16Array, sampleRateHz: number): ArrayBuffer {
  const buffer = new ArrayBuffer(44 + samples.byteLength);
  const view = new DataView(buffer);
  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + samples.byteLength, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRateHz, true);
  view.setUint32(28, sampleRateHz * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, samples.byteLength, true);
  for (let index = 0; index < samples.length; index += 1) view.setInt16(44 + index * 2, samples[index]!, true);
  return buffer;
}

function writeAscii(view: DataView, offset: number, value: string): void {
  for (let index = 0; index < value.length; index += 1) view.setUint8(offset + index, value.charCodeAt(index));
}
