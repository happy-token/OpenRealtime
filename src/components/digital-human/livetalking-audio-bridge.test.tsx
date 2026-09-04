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
      body: JSON.stringify({ sessionid: "session-9" }),
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
