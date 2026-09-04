import type { AvatarAudioChunk, AvatarAudioSink } from "@/voice/audio/avatar-output";

type Fetcher = typeof fetch;

interface BufferedGeneration {
  sampleRateHz: number;
  chunks: string[];
  onStarted: () => void;
  onEnded: () => void;
}

interface ActiveGeneration {
  controller: AbortController;
  endTimer: ReturnType<typeof setTimeout> | null;
  onEnded: () => void;
}

interface VolumeTarget {
  volume: number;
}

const WAV2LIP_RENDER_BUFFER_MS = 700;

/** Sends OpenRealtime TTS audio to LiveTalking's Wav2Lip renderer. */
export class LiveTalkingAudioBridge implements AvatarAudioSink {
  private baseUrl = "";
  private sessionId = "";
  private video: VolumeTarget | null = null;
  private volume = 0.8;
  private readonly buffered = new Map<number, BufferedGeneration>();
  private readonly active = new Map<number, ActiveGeneration>();

  constructor(private readonly fetcher: Fetcher = fetch) {}

  connect(baseUrl: string, sessionId: string, video?: VolumeTarget): void {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.sessionId = sessionId;
    this.video = video ?? null;
    if (this.video) this.video.volume = this.volume;
  }

  enqueue(chunk: AvatarAudioChunk): boolean {
    if (!this.baseUrl || !this.sessionId || chunk.sampleRateHz <= 0) return false;
    const current = this.buffered.get(chunk.generation);
    if (current && current.sampleRateHz !== chunk.sampleRateHz) {
      this.buffered.delete(chunk.generation);
      return false;
    }
    const generation = current ?? {
      sampleRateHz: chunk.sampleRateHz,
      chunks: [],
      onStarted: chunk.onStarted,
      onEnded: chunk.onEnded,
    };
    if (chunk.pcm16Base64) generation.chunks.push(chunk.pcm16Base64);
    generation.onEnded = chunk.onEnded;
    this.buffered.set(chunk.generation, generation);
    return true;
  }

  completeGeneration(generation: number): boolean {
    if (this.active.has(generation)) return true;
    const buffered = this.buffered.get(generation);
    if (!this.baseUrl || !this.sessionId || !buffered || buffered.chunks.length === 0) return false;
    this.buffered.delete(generation);

    const sourcePcm = decodePcm16Chunks(buffered.chunks);
    const wav2LipPcm = resamplePcm16(sourcePcm, buffered.sampleRateHz, 16_000);
    const wav = pcm16ToWav(wav2LipPcm, 16_000);
    const controller = new AbortController();
    this.active.set(generation, { controller, endTimer: null, onEnded: buffered.onEnded });
    const form = new FormData();
    form.append("file", new Blob([wav], { type: "audio/wav" }), `response-${generation}.wav`);
    form.append("sessionid", this.sessionId);
    const request = this.fetcher;
    void request(`${this.baseUrl}/humanaudio`, {
      method: "POST",
      body: form,
      signal: controller.signal,
    }).then(async (response) => {
      const payload = await response.json() as { code?: number; msg?: string };
      if (!response.ok || payload.code !== 0) throw new Error(payload.msg || "Wav2Lip audio upload failed");
      if (!this.active.has(generation)) return;
      buffered.onStarted();
      const audioDurationMs = wav2LipPcm.length / 16_000 * 1000;
      const endTimer = setTimeout(() => {
        const active = this.active.get(generation);
        if (!active) return;
        this.active.delete(generation);
        active.onEnded();
      }, WAV2LIP_RENDER_BUFFER_MS + audioDurationMs);
      const active = this.active.get(generation);
      if (active) active.endTimer = endTimer;
    }).catch(() => {
      const active = this.active.get(generation);
      if (!active) return;
      this.clearGeneration(generation);
      active.onEnded();
    });
    return true;
  }

  cancelGeneration(generation: number): void {
    this.buffered.delete(generation);
    this.clearGeneration(generation);
    if (!this.baseUrl || !this.sessionId) return;
    const request = this.fetcher;
    void request(`${this.baseUrl}/interrupt_talk`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionid: this.sessionId }),
    }).catch(() => undefined);
  }

  isActive(generation: number): boolean {
    return this.buffered.has(generation) || this.active.has(generation);
  }

  reset(): void {
    this.buffered.clear();
    for (const generation of this.active.keys()) this.clearGeneration(generation);
  }

  disconnect(): void {
    this.reset();
    this.baseUrl = "";
    this.sessionId = "";
    this.video = null;
  }

  setVolume(volume: number): void {
    this.volume = Math.max(0, Math.min(1, volume));
    if (this.video) this.video.volume = this.volume;
  }

  private clearGeneration(generation: number): void {
    const active = this.active.get(generation);
    if (!active) return;
    active.controller.abort();
    if (active.endTimer) clearTimeout(active.endTimer);
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

function resamplePcm16(input: Int16Array, sourceRate: number, targetRate: number): Int16Array {
  if (sourceRate === targetRate || input.length < 2) return input.slice();
  const output = new Int16Array(Math.max(1, Math.round(input.length * targetRate / sourceRate)));
  const scale = sourceRate / targetRate;
  for (let index = 0; index < output.length; index += 1) {
    const position = index * scale;
    const left = Math.min(input.length - 1, Math.floor(position));
    const right = Math.min(input.length - 1, left + 1);
    const weight = position - left;
    output[index] = Math.round(input[left]! * (1 - weight) + input[right]! * weight);
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
