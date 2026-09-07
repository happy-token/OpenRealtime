import { describe, expect, it, vi } from "vitest";
import { LiveTalkingAudioBridge } from "./livetalking-audio-bridge";

function pcm16Base64(samples: number[]): string {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);
  samples.forEach((sample, index) => view.setInt16(index * 2, sample, true));
  return Buffer.from(bytes).toString("base64");
}

describe("LiveTalkingAudioBridge", () => {
  it("uploads a completed response to Wav2Lip as 16 kHz mono WAV", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ code: 0, msg: "ok" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    const bridge = new LiveTalkingAudioBridge(fetcher);
    bridge.connect("http://127.0.0.1:8010", "session-7");

    expect(bridge.enqueue({
      pcm16Base64: pcm16Base64([0, 1_000, -1_000]),
      sampleRateHz: 24_000,
      generation: 7,
      speechId: "speech-7",
      sequence: 0,
      isFinal: false,
      onStarted: vi.fn(),
      onEnded: vi.fn(),
    })).toBe(true);
    expect(bridge.enqueue({
      pcm16Base64: pcm16Base64([2_000, -2_000, 500]),
      sampleRateHz: 24_000,
      generation: 7,
      speechId: "speech-7",
      sequence: 1,
      isFinal: true,
      onStarted: vi.fn(),
      onEnded: vi.fn(),
    })).toBe(true);
    expect(bridge.completeGeneration(7)).toBe(true);

    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:8010/humanaudio");
    const form = init.body as FormData;
    expect(form.get("sessionid")).toBe("session-7");
    const audio = form.get("file") as File;
    expect(audio.name).toBe("response-7.wav");
    const wav = await audio.arrayBuffer();
    expect(new TextDecoder().decode(wav.slice(0, 4))).toBe("RIFF");
    expect(new DataView(wav).getUint32(24, true)).toBe(16_000);
  });

  it("interrupts the matching LiveTalking session on cancellation", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ code: 0 })));
    const bridge = new LiveTalkingAudioBridge(fetcher);
    bridge.connect("http://127.0.0.1:8010", "session-9");

    bridge.cancelGeneration(9);

    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    expect(fetcher).toHaveBeenCalledWith("http://127.0.0.1:8010/interrupt_talk", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ sessionid: "session-9", generation: 9 }),
    }));
  });

  it("applies conversation volume to the WebRTC media element", () => {
    const bridge = new LiveTalkingAudioBridge();
    const video = { volume: 1 };

    bridge.setVolume(0.35);
    bridge.connect("http://127.0.0.1:8010", "session-volume", video);
    expect(video.volume).toBe(0.35);

    bridge.setVolume(2);
    expect(video.volume).toBe(1);
  });
});

describe("continuous avatar audio", () => {
  it("uploads before generation completion and preserves resampling phase across chunks", async () => {
    const uploads: FormData[] = [];
    const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.body instanceof FormData) uploads.push(init.body);
      return new Response(JSON.stringify({ code: 0, state: "buffering" }));
    });
    const bridge = new LiveTalkingAudioBridge(fetcher);
    bridge.connect("http://127.0.0.1:8010", "stream");
    const samples = Array.from({ length: 19_003 }, (_, index) => index % 10_000);
    const chunk = (values: number[], sequence: number) => ({
      pcm16Base64: pcm16Base64(values), sampleRateHz: 24_000, generation: 10,
      speechId: "continuous", sequence, isFinal: false, onStarted: vi.fn(), onEnded: vi.fn(),
    });
    bridge.enqueue(chunk(samples.slice(0, 8_003), 0));
    await vi.waitFor(() => expect(uploads).toHaveLength(1));
    expect(uploads[0]!.get("final")).toBe("0");
    bridge.enqueue(chunk(samples.slice(8_003), 1));
    bridge.completeGeneration(10);
    await vi.waitFor(() => expect(uploads).toHaveLength(3));
    expect(uploads.map((form) => form.get("sequence"))).toEqual(["0", "1", "2"]);
    expect(uploads[2]!.get("final")).toBe("1");
    const actual: number[] = [];
    for (const upload of uploads) {
      const file = upload.get("file") as File | null;
      if (!file) continue;
      const view = new DataView(await file.arrayBuffer());
      for (let offset = 44; offset < view.byteLength; offset += 2) actual.push(view.getInt16(offset, true));
    }
    const expected = Array.from({ length: Math.round(samples.length * 2 / 3) }, (_, index) => {
      const position = index * 1.5;
      const left = Math.floor(position);
      return Math.round(samples[left]! * (1 - (position - left)) + samples[Math.min(left + 1, samples.length - 1)]! * (position - left));
    });
    expect(actual).toEqual(expected);
    bridge.disconnect();
  });

  it("uses renderer playback progress for callbacks rather than upload acknowledgement", async () => {
    vi.useFakeTimers();
    let state = "buffering";
    const started = vi.fn();
    const ended = vi.fn();
    const bridge = new LiveTalkingAudioBridge(async () => new Response(JSON.stringify({ code: 0, state })));
    try {
      bridge.connect("http://127.0.0.1:8010", "status");
      bridge.enqueue({ pcm16Base64: pcm16Base64([1, 2, 3]), sampleRateHz: 16_000,
        generation: 11, speechId: "status", sequence: 0, isFinal: true, onStarted: started, onEnded: ended });
      bridge.completeGeneration(11);
      await vi.advanceTimersByTimeAsync(150);
      expect(started).not.toHaveBeenCalled();
      state = "playing";
      await vi.advanceTimersByTimeAsync(150);
      expect(started).toHaveBeenCalledTimes(1);
      expect(ended).not.toHaveBeenCalled();
      state = "completed";
      await vi.advanceTimersByTimeAsync(150);
      expect(ended).toHaveBeenCalledTimes(1);
      expect(bridge.isActive(11)).toBe(false);
    } finally {
      bridge.disconnect();
      vi.useRealTimers();
    }
  });
});

it("does not let the final resampling boundary move backwards at 44.1 kHz", async () => {
  const bridge = new LiveTalkingAudioBridge(async () => new Response(JSON.stringify({ code: 0, state: "buffering" })));
  bridge.connect("http://127.0.0.1:8010", "fractional-rate");
  bridge.enqueue({ pcm16Base64: pcm16Base64(new Array(14_116).fill(20)), sampleRateHz: 44_100,
    generation: 12, speechId: "fractional-rate", sequence: 0, isFinal: true, onStarted: vi.fn(), onEnded: vi.fn() });
  expect(() => bridge.completeGeneration(12)).not.toThrow();
  bridge.disconnect();
});

it("calls an injected native fetch without binding it to the bridge", async () => {
  const receivers: unknown[] = [];
  const request = function(this: unknown): Promise<Response> {
    receivers.push(this);
    return Promise.resolve(new Response(JSON.stringify({ code: 0, state: "buffering" })));
  };
  const bridge = new LiveTalkingAudioBridge(request);
  bridge.connect("http://127.0.0.1:8010", "native-fetch");
  bridge.enqueue({ pcm16Base64: pcm16Base64([1, 2]), sampleRateHz: 16_000, generation: 13,
    speechId: "native-fetch", sequence: 0, isFinal: true, onStarted: vi.fn(), onEnded: vi.fn() });
  bridge.completeGeneration(13);
  await vi.waitFor(() => expect(receivers).toHaveLength(1));
  expect(receivers[0]).toBeUndefined();
  bridge.disconnect();
});
