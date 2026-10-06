import { parseServerFrame, type ServerToClientFrame } from "@/lib/frames";
import type { SessionHelloV2 } from "../protocol/v2";

const RECONNECT_DELAY_MS_INITIAL = 500;
const RECONNECT_DELAY_MS_MAX = 8000;
const SOCKET_OPEN = 1;

export type VoiceSessionConnectionState =
  | "connecting"
  | "open"
  | "reconnecting"
  | "error";

export function connectionStateForAttempt(
  everOpened: boolean,
): "connecting" | "reconnecting" {
  return everOpened ? "reconnecting" : "connecting";
}

interface VoiceSessionTransportController {
  createHello(): SessionHelloV2;
  disconnected(): void;
}

interface BrowserSocket {
  readyState: number;
  addEventListener(
    type: "open" | "close" | "error" | "message",
    listener: (event: { data?: string }) => void,
  ): void;
  send(payload: string): void;
  close(code?: number, reason?: string): void;
}

export interface BrowserVoiceSessionTransportOptions {
  url: string;
  controller: VoiceSessionTransportController;
  onConnectionState: (state: VoiceSessionConnectionState) => void;
  onFrame: (frame: ServerToClientFrame) => void;
  onOpen?: () => void;
  onDisconnected?: () => void;
  createSocket?: (url: string) => BrowserSocket;
  now?: () => number;
  schedule?: (callback: () => void, delayMs: number) => unknown;
  cancelScheduled?: (handle: unknown) => void;
}

export class BrowserVoiceSessionTransport {
  private readonly options: BrowserVoiceSessionTransportOptions;
  private readonly createSocket: (url: string) => BrowserSocket;
  private readonly now: () => number;
  private readonly schedule: (callback: () => void, delayMs: number) => unknown;
  private readonly cancelScheduled: (handle: unknown) => void;
  private socket: BrowserSocket | null = null;
  private reconnectHandle: unknown = null;
  private reconnectDelayMs = RECONNECT_DELAY_MS_INITIAL;
  private everOpened = false;
  private disposed = false;
  private reconnectAllowed = true;
  private disconnectStartedAtMs: number | null = null;
  private reconnectCount = 0;
  private maxDisconnectMs = 0;

  constructor(options: BrowserVoiceSessionTransportOptions) {
    this.options = options;
    this.createSocket = options.createSocket
      ?? ((url) => new WebSocket(url) as unknown as BrowserSocket);
    this.now = options.now ?? (() => performance.now());
    this.schedule = options.schedule ?? ((callback, delayMs) => (
      window.setTimeout(callback, delayMs)
    ));
    this.cancelScheduled = options.cancelScheduled ?? ((handle) => {
      window.clearTimeout(handle as number);
    });
  }

  get isOpen(): boolean {
    return this.socket?.readyState === SOCKET_OPEN;
  }

  start(): void {
    this.disposed = false;
    this.reconnectAllowed = true;
    this.connect();
  }

  send(frame: unknown): boolean {
    const socket = this.socket;
    if (!socket || socket.readyState !== SOCKET_OPEN) return false;
    socket.send(JSON.stringify(frame));
    return true;
  }

  reconnect(): void {
    this.socket?.close();
  }

  retryNow(): void {
    if (this.disposed) return;
    this.reconnectAllowed = true;
    if (this.reconnectHandle !== null) {
      this.cancelScheduled(this.reconnectHandle);
      this.reconnectHandle = null;
    }
    const previous = this.socket;
    this.socket = null;
    previous?.close();
    this.connect();
  }

  reportRecovered(): boolean {
    if (this.disconnectStartedAtMs === null || !this.isOpen) return false;
    const downtimeMs = Math.max(0, this.now() - this.disconnectStartedAtMs);
    this.maxDisconnectMs = Math.max(this.maxDisconnectMs, downtimeMs);
    const sent = this.send({
      type: "client_connection_quality",
      reconnect_count: this.reconnectCount,
      last_disconnect_ms: Math.round(downtimeMs * 10) / 10,
      max_disconnect_ms: Math.round(this.maxDisconnectMs * 10) / 10,
    });
    if (sent) this.disconnectStartedAtMs = null;
    return sent;
  }

  dispose(): void {
    this.disposed = true;
    if (this.reconnectHandle !== null) {
      this.cancelScheduled(this.reconnectHandle);
      this.reconnectHandle = null;
    }
    this.socket?.close(1000, "client_dispose");
    this.socket = null;
  }

  private connect(): void {
    if (this.disposed) return;
    this.options.onConnectionState(connectionStateForAttempt(this.everOpened));
    const socket = this.createSocket(this.options.url);
    this.socket = socket;

    socket.addEventListener("open", () => {
      if (this.disposed || this.socket !== socket) return;
      this.reconnectDelayMs = RECONNECT_DELAY_MS_INITIAL;
      this.everOpened = true;
      socket.send(JSON.stringify(this.options.controller.createHello()));
      this.options.onConnectionState("open");
      this.options.onOpen?.();
    });
    socket.addEventListener("close", () => {
      if (this.disposed || this.socket !== socket) return;
      this.options.controller.disconnected();
      this.options.onDisconnected?.();
      if (!this.reconnectAllowed) {
        this.socket = null;
        this.options.onConnectionState("error");
        return;
      }
      if (this.everOpened && this.disconnectStartedAtMs === null) {
        this.disconnectStartedAtMs = this.now();
        this.reconnectCount += 1;
      }
      this.options.onConnectionState(connectionStateForAttempt(this.everOpened));
      this.reconnectHandle = this.schedule(() => {
        this.reconnectHandle = null;
        this.connect();
      }, this.reconnectDelayMs);
      this.reconnectDelayMs = Math.min(
        this.reconnectDelayMs * 2,
        RECONNECT_DELAY_MS_MAX,
      );
    });
    socket.addEventListener("error", () => {
      if (!this.disposed && this.socket === socket) {
        this.options.onConnectionState("error");
      }
    });
    socket.addEventListener("message", (event) => {
      if (this.disposed || this.socket !== socket || typeof event.data !== "string") return;
      let rawFrame: unknown;
      try {
        rawFrame = JSON.parse(event.data);
      } catch {
        console.warn("Ignored malformed OpenRealtime WebSocket JSON frame");
        return;
      }
      const frame = parseServerFrame(rawFrame);
      if (!frame) {
        console.warn("Ignored unsupported or invalid OpenRealtime WebSocket frame");
        return;
      }
      if (
        frame.type === "voice_session_failed"
        && frame.session_disposition === "close"
      ) {
        this.reconnectAllowed = false;
      }
      this.options.onFrame(frame);
    });
  }
}
