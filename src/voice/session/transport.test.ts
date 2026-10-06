import { describe, expect, it } from "vitest";
import { BrowserVoiceSessionTransport } from "./transport";

class FakeSocket {
  readyState = 0;
  sent: string[] = [];
  listeners = new Map<string, Array<(event: { data?: string }) => void>>();

  addEventListener(type: string, listener: (event: { data?: string }) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  send(payload: string): void {
    this.sent.push(payload);
  }

  closeCode: number | undefined;
  close(code?: number): void {
    this.closeCode = code;
    this.readyState = 3;
  }

  emit(type: string, event: { data?: string } = {}): void {
    if (type === "open") this.readyState = 1;
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

describe("BrowserVoiceSessionTransport", () => {
  it("owns v2 hello, frame parsing, and reconnect state", () => {
    const sockets: FakeSocket[] = [];
    const states: string[] = [];
    const frames: string[] = [];
    const scheduled: Array<() => void> = [];
    let disconnected = 0;
    const transport = new BrowserVoiceSessionTransport({
      url: "ws://voice.test",
      controller: {
        createHello: () => ({
          type: "session_hello",
          supported_protocol_versions: [2],
          resume_session_id: null,
          resume_token: null,
          last_session_sequence: 0,
          last_journal_sequence: 0,
        }),
        disconnected: () => { disconnected += 1; },
      },
      createSocket: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      schedule: (callback) => {
        scheduled.push(callback);
        return callback;
      },
      cancelScheduled: () => undefined,
      onConnectionState: (state) => states.push(state),
      onFrame: (frame) => frames.push(frame.type),
    });

    transport.start();
    sockets[0].emit("open");
    sockets[0].emit("message", {
      data: JSON.stringify({
        type: "session_ack",
        session_id: "voice-1",
        resumed: false,
        protocol_version: 2,
        resume_token: "token-1",
      }),
    });
    sockets[0].emit("close");

    expect(states).toEqual(["connecting", "open", "reconnecting"]);
    expect(JSON.parse(sockets[0].sent[0])).toMatchObject({
      type: "session_hello",
      supported_protocol_versions: [2],
    });
    expect(frames).toEqual(["session_ack"]);
    expect(disconnected).toBe(1);
    expect(scheduled).toHaveLength(1);

    scheduled[0]();
    expect(sockets).toHaveLength(2);
  });

  it("reports recovered connection timing from the transport clock", () => {
    const socket = new FakeSocket();
    const times = [100, 760];
    const transport = new BrowserVoiceSessionTransport({
      url: "ws://voice.test",
      controller: {
        createHello: () => ({
          type: "session_hello",
          supported_protocol_versions: [2],
          resume_session_id: null,
          resume_token: null,
          last_session_sequence: 0,
          last_journal_sequence: 0,
        }),
        disconnected: () => undefined,
      },
      createSocket: () => socket,
      now: () => times.shift() ?? 760,
      schedule: () => 1,
      cancelScheduled: () => undefined,
      onConnectionState: () => undefined,
      onFrame: () => undefined,
    });

    transport.start();
    socket.emit("open");
    socket.emit("close");
    socket.readyState = 1;

    expect(transport.reportRecovered()).toBe(true);
    expect(JSON.parse(socket.sent.at(-1) ?? "{}")).toEqual({
      type: "client_connection_quality",
      reconnect_count: 1,
      last_disconnect_ms: 660,
      max_disconnect_ms: 660,
    });
  });

  it("retries immediately after a terminal failure when the user asks", () => {
    const sockets: FakeSocket[] = [];
    const states: string[] = [];
    const transport = new BrowserVoiceSessionTransport({
      url: "ws://voice.test",
      controller: {
        createHello: () => ({
          type: "session_hello",
          supported_protocol_versions: [2],
          resume_session_id: null,
          resume_token: null,
          last_session_sequence: 0,
          last_journal_sequence: 0,
        }),
        disconnected: () => undefined,
      },
      createSocket: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      schedule: () => 1,
      cancelScheduled: () => undefined,
      onConnectionState: (state) => states.push(state),
      onFrame: () => undefined,
    });

    transport.start();
    sockets[0].emit("open");
    sockets[0].emit("message", {
      data: JSON.stringify({
        type: "voice_session_failed",
        error_id: "failure-1",
        code: "authentication_failed",
        phase: "starting",
        retryable: false,
        retry_after_ms: null,
        session_disposition: "close",
        safe_message: "连接身份验证失败。",
      }),
    });
    sockets[0].emit("close");

    transport.retryNow();
    expect(sockets).toHaveLength(2);
    expect(states.at(-1)).toBe("reconnecting");
    sockets[1].emit("open");
    expect(states.at(-1)).toBe("open");
  });

  it("does not reconnect after a terminal voice-session failure", () => {
    const socket = new FakeSocket();
    const states: string[] = [];
    const frames: string[] = [];
    const scheduled: Array<() => void> = [];
    const transport = new BrowserVoiceSessionTransport({
      url: "ws://voice.test",
      controller: {
        createHello: () => ({
          type: "session_hello",
          supported_protocol_versions: [2],
          resume_session_id: null,
          resume_token: null,
          last_session_sequence: 0,
          last_journal_sequence: 0,
        }),
        disconnected: () => undefined,
      },
      createSocket: () => socket,
      schedule: (callback) => {
        scheduled.push(callback);
        return callback;
      },
      cancelScheduled: () => undefined,
      onConnectionState: (state) => states.push(state),
      onFrame: (frame) => frames.push(frame.type),
    });

    transport.start();
    socket.emit("open");
    socket.emit("message", {
      data: JSON.stringify({
        type: "voice_session_failed",
        error_id: "failure-1",
        code: "authentication_failed",
        phase: "starting",
        retryable: false,
        retry_after_ms: null,
        session_disposition: "close",
        safe_message: "连接身份验证失败。",
      }),
    });
    socket.emit("close");

    expect(frames).toEqual(["voice_session_failed"]);
    expect(states.at(-1)).toBe("error");
    expect(scheduled).toHaveLength(0);
  });
});

it("marks intentional disposal as a normal WebSocket close", () => {
  const socket = new FakeSocket();
  const transport = new BrowserVoiceSessionTransport({ url: "ws://test", controller: { createHello: () => ({ type: "session_hello", protocol_version: 2 } as never), disconnected: () => {} }, onConnectionState: () => {}, onFrame: () => {}, createSocket: () => socket });
  transport.start();
  socket.emit("open");
  transport.dispose();
  expect(socket.closeCode).toBe(1000);
});
