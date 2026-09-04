import { describe, expect, it, vi } from "vitest";
import { LiveTalkingSession } from "./livetalking-session";

describe("LiveTalkingSession", () => {
  it("sends the prepared avatar binding with the WebRTC offer", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      expect(body.avatar).toBe("wav2lip96-anchor-a1b2c3d4");
      return new Response(JSON.stringify({ sdp: "answer", type: "answer", sessionid: "1" }));
    }) as unknown as typeof fetch;
    const peer = {
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addTransceiver: vi.fn(),
      createOffer: vi.fn(async () => ({ sdp: "offer", type: "offer" })),
      setLocalDescription: vi.fn(async function (this: { localDescription?: RTCSessionDescriptionInit }, description) {
        this.localDescription = description;
      }),
      setRemoteDescription: vi.fn(async () => undefined),
      close: vi.fn(),
      connectionState: "connected",
      iceGatheringState: "complete",
      localDescription: null as RTCSessionDescriptionInit | null,
    };
    vi.stubGlobal("RTCPeerConnection", vi.fn(() => peer));
    vi.stubGlobal("MediaStream", vi.fn(() => ({ addTrack: vi.fn() })));

    const video = { play: vi.fn(async () => undefined), srcObject: null } as unknown as HTMLVideoElement;
    const session = new LiveTalkingSession("http://127.0.0.1:8010", fetcher, "wav2lip96-anchor-a1b2c3d4");
    const connecting = session.connect(video);
    const trackListener = peer.addEventListener.mock.calls.find(([name]) => name === "track")?.[1];
    trackListener?.({ track: { kind: "video" } });

    await expect(connecting).resolves.toEqual({ sessionId: "1" });
    vi.unstubAllGlobals();
  });

  it("reports a non-JSON renderer error without exposing parser internals", async () => {
    const fetcher = vi.fn(async () => new Response(
      "<pre>missing avatar</pre>",
      { status: 404, headers: { "Content-Type": "text/html" } },
    )) as unknown as typeof fetch;
    const peer = {
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addTransceiver: vi.fn(),
      createOffer: vi.fn(async () => ({ sdp: "offer", type: "offer" })),
      setLocalDescription: vi.fn(async function (this: { localDescription?: RTCSessionDescriptionInit }, description) {
        this.localDescription = description;
      }),
      close: vi.fn(),
      iceGatheringState: "complete",
      localDescription: null as RTCSessionDescriptionInit | null,
    };
    vi.stubGlobal("RTCPeerConnection", vi.fn(() => peer));
    vi.stubGlobal("MediaStream", vi.fn(() => ({ addTrack: vi.fn() })));

    const video = { play: vi.fn(async () => undefined), srcObject: null } as unknown as HTMLVideoElement;
    const session = new LiveTalkingSession("http://127.0.0.1:8010", fetcher, "missing-avatar");

    await expect(session.connect(video)).rejects.toThrow("实时数字人驱动请求失败（HTTP 404）");
    vi.unstubAllGlobals();
  });
});
