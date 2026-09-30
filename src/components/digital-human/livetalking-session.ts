import { readJsonResponse } from "@/lib/http-json-response";

interface LiveTalkingAnswer {
  code?: number;
  msg?: string;
  sdp?: string;
  sessionid?: string | number;
}

/** Owns the browser WebRTC receive session used by LiveTalking/Wav2Lip. */
export class LiveTalkingSession {
  private peer: RTCPeerConnection | null = null;
  private video: HTMLVideoElement | null = null;

  constructor(
    private readonly baseUrl: string,
    private readonly fetcher: typeof fetch = fetch,
    private readonly avatarId?: string,
    private readonly onDisconnected?: (error: Error) => void,
  ) {}

  async connect(video: HTMLVideoElement): Promise<{ sessionId: string }> {
    this.stop();
    this.video = video;
    const peer = new RTCPeerConnection();
    this.peer = peer;
    const media = new MediaStream();
    video.srcObject = media;
    let receivedVideo = false;

    peer.addEventListener("track", (event) => {
      if (this.peer !== peer) return;
      media.addTrack(event.track);
      if (event.track.kind === "video") receivedVideo = true;
      void video.play().catch(() => undefined);
    });
    peer.addTransceiver("video", { direction: "recvonly" });
    peer.addTransceiver("audio", { direction: "recvonly" });
    const offer = await peer.createOffer();
    await peer.setLocalDescription(offer);
    await waitForIceGathering(peer);
    const local = peer.localDescription;
    if (!local) throw new Error("LiveTalking WebRTC offer 创建失败");

    const request = this.fetcher;
    const response = await request(`${this.baseUrl.replace(/\/$/, "")}/offer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sdp: local.sdp,
        type: local.type,
        ...(this.avatarId ? { avatar: this.avatarId } : {}),
      }),
    });
    const answer = await readJsonResponse<LiveTalkingAnswer>(
      response,
      "实时数字人驱动请求失败",
    );
    if (!response.ok || (answer.code != null && answer.code !== 0) || !answer.sdp || answer.sessionid == null) {
      throw new Error(answer.msg || "LiveTalking WebRTC 应答无效");
    }
    await peer.setRemoteDescription({ type: "answer", sdp: answer.sdp });
    await waitForConnectedVideo(peer, () => receivedVideo);
    if (this.peer !== peer) throw new Error("LiveTalking 会话已停止");
    peer.addEventListener("connectionstatechange", () => {
      if (this.peer !== peer) return;
      if (["disconnected", "failed", "closed"].includes(peer.connectionState)) {
        this.stop();
        this.onDisconnected?.(new Error("数字人视频连接已中断，已切换普通音频，请重连画面。"));
      }
    });
    return { sessionId: String(answer.sessionid) };
  }

  stop(): void {
    const peer = this.peer;
    this.peer = null;
    peer?.close();
    if (this.video) this.video.srcObject = null;
    this.video = null;
  }
}

function waitForIceGathering(peer: RTCPeerConnection): Promise<void> {
  if (peer.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => finish(new Error("LiveTalking ICE gathering 超时")), 10_000);
    const check = () => {
      if (peer.iceGatheringState === "complete") finish();
    };
    const finish = (error?: Error) => {
      clearTimeout(timeout);
      peer.removeEventListener("icegatheringstatechange", check);
      if (error) reject(error);
      else resolve();
    };
    peer.addEventListener("icegatheringstatechange", check);
  });
}

function waitForConnectedVideo(
  peer: RTCPeerConnection,
  hasVideo: () => boolean,
): Promise<void> {
  if (peer.connectionState === "connected" && hasVideo()) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => finish(new Error("LiveTalking 视频流连接超时")), 15_000);
    const check = () => {
      if (peer.connectionState === "failed" || peer.connectionState === "closed") {
        finish(new Error("LiveTalking WebRTC 连接失败"));
      } else if (peer.connectionState === "connected" && hasVideo()) {
        finish();
      }
    };
    const finish = (error?: Error) => {
      clearTimeout(timeout);
      peer.removeEventListener("connectionstatechange", check);
      peer.removeEventListener("track", check);
      if (error) reject(error);
      else resolve();
    };
    peer.addEventListener("connectionstatechange", check);
    peer.addEventListener("track", check);
  });
}
