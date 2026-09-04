import { test, expect, type Page } from "@playwright/test";

async function enterContentPageForm(page: Page) {
  const pageFormTrigger = page.getByRole("button", { name: /^页面形态：/ });
  await pageFormTrigger.hover();
  const pageFormMenu = page.getByRole("menu", { name: "页面形态" });
  await expect(pageFormMenu).toBeVisible();
  const triggerBox = await pageFormTrigger.boundingBox();
  const menuBox = await pageFormMenu.boundingBox();
  expect(triggerBox).not.toBeNull();
  expect(menuBox).not.toBeNull();
  expect(Math.abs(
    (triggerBox!.x + triggerBox!.width / 2) - (menuBox!.x + menuBox!.width / 2),
  )).toBeLessThan(2);
  const firstOption = pageFormMenu.getByRole("menuitemradio").first();
  const diagramBox = await firstOption.locator(".session-layout-diagram").boundingBox();
  const labelBox = await firstOption.locator("span").nth(1).boundingBox();
  expect(diagramBox).not.toBeNull();
  expect(labelBox).not.toBeNull();
  expect(labelBox!.y).toBeGreaterThanOrEqual(diagramBox!.y + diagramBox!.height);
  await page.getByRole("menuitemradio", { name: /内容/ }).click();
}

test("startup smoke: root page responds 200, not a dev-server error page", async ({ page }) => {
  // Guards against Next.js dev-cache/HMR desync (e.g. the
  // "Expected clientReferenceManifest to be defined" InvariantError seen
  // after a long-running dev server survived many file edits) — that
  // failure mode renders as a 500 on this exact route.
  const response = await page.goto("/");
  expect(response?.status()).toBe(200);
  await expect(page.locator(".brand")).toBeVisible();
});

test("loads, toggles view, and shows connecting mic state without a backend", async ({ page }) => {
  await page.addInitScript(() => {
    class NeverOpeningWebSocket {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSING = 2;
      static readonly CLOSED = 3;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSING = 2;
      readonly CLOSED = 3;
      readyState = NeverOpeningWebSocket.CONNECTING;

      addEventListener() {}
      send() {}
      close() {
        this.readyState = NeverOpeningWebSocket.CLOSED;
      }
    }

    window.WebSocket = NeverOpeningWebSocket as unknown as typeof WebSocket;
  });
  await page.goto("/");

  await expect(page.locator(".brand")).toBeVisible();

  const startButton = page.getByRole("button", { name: "正在连接语音服务" });
  await expect(startButton).toBeDisabled();
  await expect(page.getByText("语音服务准备中…")).toBeVisible();
  await expect(page.getByRole("tab", { name: "聊天" })).toHaveCount(0);
});

test("browser speech fallback streams user and assistant text", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("openrealtime-workbench-transparency", "82");
    window.localStorage.setItem("openrealtime-workbench-glass-blur", "14");

    type Listener = (event: Event | MessageEvent<string>) => void;

    class FakeWebSocket {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSING = 2;
      static readonly CLOSED = 3;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSING = 2;
      readonly CLOSED = 3;
      readyState = FakeWebSocket.CONNECTING;
      private listeners = new Map<string, Listener[]>();

      constructor() {
        setTimeout(() => {
          this.readyState = FakeWebSocket.OPEN;
          this.emit("open", new Event("open"));
        }, 0);
      }

      addEventListener(type: string, listener: Listener) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }

      send(raw: string) {
        const frame = JSON.parse(raw) as { type: string; text?: string };
        if (frame.type === "session_hello") {
          this.message({ type: "session_ack", session_id: "e2e", resumed: false });
          this.message({
            type: "session_capabilities",
            server_asr: false,
            server_tts: false,
            assistant_text_streaming: true,
            user_transcript_streaming: false,
          });
          return;
        }
        if (frame.type === "user_text") {
          setTimeout(
            () => this.message({ type: "assistant_text", text: "收", generation: 1 }),
            40,
          );
          setTimeout(
            () =>
              this.message({
                type: "assistant_text",
                text: `**收到**：${frame.text}，[详情](https://example.com)`,
                generation: 1,
              }),
            80,
          );
          setTimeout(
            () => this.message({ type: "assistant_response_completed", generation: 1 }),
            120,
          );
        }
      }

      close() {
        this.readyState = FakeWebSocket.CLOSED;
        this.emit("close", new Event("close"));
      }

      private message(frame: object) {
        this.emit(
          "message",
          new MessageEvent("message", { data: JSON.stringify(frame) }),
        );
      }

      private emit(type: string, event: Event | MessageEvent<string>) {
        for (const listener of this.listeners.get(type) ?? []) listener(event);
      }
    }

    class FakeSpeechRecognition {
      continuous = true;
      interimResults = true;
      lang = "zh-CN";
      onresult: ((event: object) => void) | null = null;
      onerror: ((event: object) => void) | null = null;
      onend: (() => void) | null = null;

      start() {
        setTimeout(
          () =>
            this.onresult?.({
              resultIndex: 0,
              results: [Object.assign([{ transcript: "今天北" }], { isFinal: false })],
            }),
          100,
        );
        setTimeout(
          () =>
            this.onresult?.({
              resultIndex: 0,
              results: [
                Object.assign([{ transcript: "今天北京天气怎么样" }], {
                  isFinal: true,
                }),
              ],
            }),
          300,
        );
      }

      stop() {}
      abort() {}
    }

    const browserWindow = window as typeof window & {
      WebSocket: typeof WebSocket;
      SpeechRecognition: typeof FakeSpeechRecognition;
      webkitSpeechRecognition: typeof FakeSpeechRecognition;
      __spoken: string[];
    };
    browserWindow.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    browserWindow.SpeechRecognition = FakeSpeechRecognition;
    browserWindow.webkitSpeechRecognition = FakeSpeechRecognition;
    browserWindow.__spoken = [];
    window.speechSynthesis.speak = (utterance: SpeechSynthesisUtterance) => {
      browserWindow.__spoken.push(utterance.text);
      utterance.dispatchEvent(new Event("end"));
    };
  });

  await page.goto("/");
  const mic = page.getByRole("button", { name: "主页开始对话" });
  await expect(mic).toBeEnabled();
  await mic.click();

  const sessionControls = page.locator(".session-control-shell");
  await expect(sessionControls).toHaveAttribute("data-transparency", "82");
  await expect(sessionControls).toHaveAttribute("data-glass-blur", "14");

  const visualCluster = page.locator(".orb-motion-cluster");
  await expect(visualCluster.locator(".orb")).toBeVisible();
  await expect(visualCluster.locator(".orb-conversation-status")).toBeVisible();
  await expect(visualCluster).toHaveCSS("animation-name", "orb-cluster-float");
  await expect(page.locator(".orb-library-mount")).toHaveCSS("animation-name", "none");
  const caption = page.locator(".current-turn-text");
  await expect(caption).toContainText("今天北");
  await expect(caption).toHaveCSS("position", "absolute");
  const compactControlWidth = await sessionControls.evaluate((element) => element.getBoundingClientRect().width);
  await page.getByRole("button", { name: "展开文字输入" }).click();
  await expect(page.getByRole("textbox", { name: "输入对话消息" })).toBeVisible();
  await expect.poll(async () => sessionControls.evaluate((element) => element.getBoundingClientRect().width))
    .toBeGreaterThan(compactControlWidth + 120);
  await page.getByRole("button", { name: "收起文字输入" }).click();
  await enterContentPageForm(page);
  await page.waitForTimeout(500);
  const compactSurface = page.getByRole("region", { name: "实时展示" });
  const compactSurfaceControls = page.getByRole("toolbar", { name: "小窗显示控制" });
  await expect(compactSurfaceControls).toHaveCSS("opacity", "0");
  await compactSurface.hover();
  await expect(compactSurfaceControls).toHaveCSS("opacity", "1");
  await expect(compactSurfaceControls.getByRole("button")).toHaveCount(3);
  await expect(page.locator(".bubble--user")).toContainText(
    "今天北京天气怎么样",
  );
  await expect(page.locator(".bubble--assistant")).toHaveText(
    "收到：今天北京天气怎么样，详情",
  );
  await expect(page.locator(".bubble--assistant")).toHaveAttribute("data-status", "completed");
  await expect
    .poll(() => page.evaluate(() => (window as typeof window & { __spoken: string[] }).__spoken))
    .toEqual(["收到：今天北京天气怎么样，详情"]);

  await expect(sessionControls.locator(".session-action-btn")).toHaveCount(6);
  await expect(page.getByRole("button", { name: "返回内容形态" })).toHaveCount(0);
  const settingsButton = page.getByRole("button", { name: "会话设置" });
  await settingsButton.hover();
  await expect.poll(() => settingsButton.evaluate((element) => ({
    content: window.getComputedStyle(element, "::after").content,
    opacity: window.getComputedStyle(element, "::after").opacity,
  }))).toEqual({ content: '"会话设置"', opacity: "1" });
  await settingsButton.click();
  const sessionWorkbench = page.getByRole("dialog", { name: "会话配置工作台" });
  await expect(sessionWorkbench).toBeVisible();
  await expect(sessionWorkbench).toHaveAttribute("data-variant", "session");
  await expect(sessionWorkbench).toHaveAttribute("data-session-mode", "voice");
  await expect(sessionWorkbench).toHaveAttribute("style", /--panel-surface-alpha: 0\.18/);
  await expect(sessionWorkbench.getByRole("tab", { name: "呈现" })).toBeVisible();
  await expect(sessionWorkbench.getByRole("tab", { name: "音色" })).toBeVisible();
  await expect(sessionWorkbench.getByText("体验配置", { exact: true })).toHaveCount(0);
  await expect(sessionWorkbench.getByLabel("体验预览")).toHaveCount(0);
  await sessionWorkbench.getByRole("button", { name: "关闭设置" }).click();
});

test("server ASR captures microphone PCM and completes a voice turn", async ({ page }) => {
  await page.addInitScript(() => {
    type Listener = (event: Event | MessageEvent<string>) => void;

    class FakeWebSocket {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSING = 2;
      static readonly CLOSED = 3;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSING = 2;
      readonly CLOSED = 3;
      readyState = FakeWebSocket.CONNECTING;
      sentSessionHello = false;
      private listeners = new Map<string, Listener[]>();

      constructor() {
        const browserWindow = window as typeof window & {
          __disconnectVoiceSocket: () => void;
          __voiceSockets: FakeWebSocket[];
        };
        browserWindow.__voiceSockets.push(this);
        browserWindow.__disconnectVoiceSocket = () => {
          const socket = browserWindow.__voiceSockets.findLast(
            (candidate) => (
              candidate.readyState === FakeWebSocket.OPEN
              && candidate.sentSessionHello
            ),
          );
          if (!socket) return;
          socket.readyState = FakeWebSocket.CLOSED;
          socket.emit("close", new Event("close"));
        };
        setTimeout(() => {
          if (this.readyState !== FakeWebSocket.CONNECTING) return;
          this.readyState = FakeWebSocket.OPEN;
          this.emit("open", new Event("open"));
        }, 0);
      }

      addEventListener(type: string, listener: Listener) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }

      send(raw: string) {
        const frame = JSON.parse(raw) as {
          type: string;
          input_epoch?: string;
          sequence?: number;
          start_sample?: number;
          sample_count?: number;
          resume_session_id?: string | null;
        };
        const browserWindow = window as typeof window & {
          __sentFrames: string[];
          __inputEpochStarts: unknown[];
          __readySequence: number;
        };
        browserWindow.__sentFrames.push(frame.type);
        if (frame.type === "session_hello") {
          this.sentSessionHello = true;
          this.message({
            type: "session_ack",
            session_id: "server-asr-e2e",
            resumed: Boolean(frame.resume_session_id),
            protocol_version: 2,
            resume_token: "server-asr-token",
          });
          this.message({
            type: "session_capabilities",
            server_asr: true,
            server_tts: false,
            assistant_text_streaming: true,
            user_transcript_streaming: true,
          });
          return;
        }
        if (frame.type === "input_epoch_started") {
          browserWindow.__inputEpochStarts.push(frame);
          browserWindow.__readySequence += 1;
          this.message({
            type: "voice_session_ready",
            session_sequence: browserWindow.__readySequence,
            input_epoch: frame.input_epoch,
          });
          return;
        }
        if (frame.type !== "input_audio_frame") return;
        this.message({
          type: "input_audio_ack",
          input_epoch: frame.input_epoch,
          highest_contiguous_sequence: frame.sequence,
          next_start_sample: (frame.start_sample ?? 0) + (frame.sample_count ?? 0),
        });
        this.message({
          type: "user_transcript",
          text: "服务端语音识别正常",
          generation: 1,
          is_final: true,
        });
        this.message({ type: "assistant_text", text: "收到", generation: 1 });
        this.message({ type: "assistant_response_completed", generation: 1 });
      }

      close() {
        if (this.readyState === FakeWebSocket.CLOSED) return;
        this.readyState = FakeWebSocket.CLOSED;
        this.emit("close", new Event("close"));
      }

      private message(frame: object) {
        this.emit("message", new MessageEvent("message", { data: JSON.stringify(frame) }));
      }

      private emit(type: string, event: Event | MessageEvent<string>) {
        for (const listener of this.listeners.get(type) ?? []) listener(event);
      }
    }

    class FakeAudioContext {
      currentTime = 0;
      audioWorklet = { addModule: async () => undefined };

      createMediaStreamSource() {
        return { connect: () => undefined };
      }

      createAnalyser() {
        return {
          fftSize: 0,
          getByteTimeDomainData: (samples: Uint8Array) => samples.fill(128),
        };
      }

      async close() {}
    }

    class FakeAudioWorkletNode {
      private inputEpoch = "";
      port: {
        onmessage: ((event: MessageEvent<unknown>) => void) | null;
        postMessage: (command: { type: string; input_epoch?: string }) => void;
      } = {
        onmessage: null,
        postMessage: (command) => {
          if (command.type === "begin_epoch") this.inputEpoch = command.input_epoch ?? "";
          if (command.type !== "release") return;
          setTimeout(() => {
            this.port.onmessage?.(
              new MessageEvent("message", {
                data: {
                  type: "audio_frame",
                  inputEpoch: this.inputEpoch,
                  captureMode: "prebuffer",
                  pcm16: new ArrayBuffer(1_024),
                },
              }),
            );
          }, 0);
        },
      };

      constructor(_context: unknown, _name: string, options: { processorOptions?: { inputEpoch?: string } }) {
        this.inputEpoch = options.processorOptions?.inputEpoch ?? "";
      }

      connect() {}
      disconnect() {}
    }

    const browserWindow = window as typeof window & {
      __sentFrames: string[];
      __inputEpochStarts: unknown[];
      __readySequence: number;
      __disconnectVoiceSocket: () => void;
      __voiceSockets: FakeWebSocket[];
      WebSocket: typeof WebSocket;
      AudioContext: typeof AudioContext;
      AudioWorkletNode: typeof AudioWorkletNode;
    };
    browserWindow.__sentFrames = [];
    browserWindow.__inputEpochStarts = [];
    browserWindow.__readySequence = 0;
    browserWindow.__voiceSockets = [];
    browserWindow.__disconnectVoiceSocket = () => undefined;
    browserWindow.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    browserWindow.AudioContext = FakeAudioContext as unknown as typeof AudioContext;
    browserWindow.AudioWorkletNode = FakeAudioWorkletNode as unknown as typeof AudioWorkletNode;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async (constraints: MediaStreamConstraints) => {
          const audio = typeof constraints.audio === "object" ? constraints.audio : {};
          const track = {
            stop: () => undefined,
            addEventListener: () => undefined,
            getSettings: () => ({
              echoCancellation: true,
              noiseSuppression: Boolean(audio.noiseSuppression),
              autoGainControl: true,
            }),
          };
          return {
            getTracks: () => [track],
            getAudioTracks: () => [track],
          };
        },
      },
    });
    window.speechSynthesis.speak = (utterance: SpeechSynthesisUtterance) => {
      utterance.dispatchEvent(new Event("end"));
    };
  });

  await page.goto("/");
  const mic = page.getByRole("button", { name: "开始语音对话" });
  await expect(mic).toBeEnabled();
  await mic.click();

  await expect
    .poll(() =>
      page.evaluate(
        () => (window as typeof window & { __sentFrames: string[] }).__sentFrames,
      ),
    )
    .toContain("input_audio_frame");
  await expect.poll(() => page.evaluate(() => (
    window as typeof window & {
      __inputEpochStarts: Array<{
        effective_constraints?: { noise_suppression?: boolean };
        effect_owners?: { noise_suppression?: string };
      }>;
    }
  ).__inputEpochStarts[0])).toMatchObject({
    effective_constraints: { noise_suppression: true },
    effect_owners: { noise_suppression: "device" },
  });
  await page.getByRole("button", { name: "会话设置" }).click();
  await page.getByRole("tab", { name: "对话" }).click();
  const noiseRow = page.locator(".drawer-row").filter({
    hasText: "浏览器降噪 / 回声消除",
  });
  await noiseRow.locator("label.switch").click();
  await expect(noiseRow.getByRole("checkbox")).not.toBeChecked();
  await expect.poll(() => page.evaluate(() => {
    const browserWindow = window as typeof window & {
      __inputEpochStarts: Array<{ input_epoch: string }>;
      __sentFrames: string[];
    };
    return {
      epochs: browserWindow.__inputEpochStarts.map((frame) => frame.input_epoch),
      epochCount: browserWindow.__inputEpochStarts.length,
      hellos: browserWindow.__sentFrames.filter((type) => type === "session_hello").length,
    };
  })).toMatchObject({ epochCount: 2, hellos: 1 });
  const rebuilt = await page.evaluate(() => (
    window as typeof window & {
      __inputEpochStarts: Array<{
        input_epoch: string;
        requested_constraints: { noise_suppression: boolean };
      }>;
    }
  ).__inputEpochStarts);
  expect(rebuilt).toHaveLength(2);
  expect(rebuilt[0].input_epoch).not.toBe(rebuilt[1].input_epoch);
  expect(rebuilt[1].requested_constraints.noise_suppression).toBe(false);
  await page.getByRole("button", { name: "关闭设置" }).click();
  await enterContentPageForm(page);
  await expect(page.locator(".bubble--user")).toContainText("服务端语音识别正常");
  await expect(page.locator(".bubble--assistant")).toContainText("收到");

  await expect.poll(() => page.evaluate(() => (
    window as typeof window & { __voiceSockets: Array<{ readyState: number }> }
  ).__voiceSockets.map((socket) => socket.readyState))).toContain(1);
  await page.evaluate(() => (
    window as typeof window & { __disconnectVoiceSocket: () => void }
  ).__disconnectVoiceSocket());
  await expect.poll(() => page.evaluate(() => (
    window as typeof window & { __voiceSockets: Array<{ readyState: number }> }
  ).__voiceSockets.map((socket) => socket.readyState))).toContain(3);
  await expect.poll(() => page.evaluate(() => {
    const browserWindow = window as typeof window & {
      __inputEpochStarts: unknown[];
      __sentFrames: string[];
    };
    return {
      epochs: browserWindow.__inputEpochStarts.length,
      hellos: browserWindow.__sentFrames.filter((type) => type === "session_hello").length,
      quality: browserWindow.__sentFrames.filter(
        (type) => type === "client_connection_quality",
      ).length,
    };
  })).toEqual({ epochs: 3, hellos: 2, quality: 1 });
});

test("terminating a reply returns idle and ignores late assistant output", async ({ page }) => {
  await page.addInitScript(() => {
    type Listener = (event: Event | MessageEvent<string>) => void;

    class FakeWebSocket {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSING = 2;
      static readonly CLOSED = 3;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSING = 2;
      readonly CLOSED = 3;
      readyState = FakeWebSocket.CONNECTING;
      private listeners = new Map<string, Listener[]>();
      private replied = false;

      constructor() {
        setTimeout(() => {
          this.readyState = FakeWebSocket.OPEN;
          this.emit("open", new Event("open"));
        }, 0);
      }

      addEventListener(type: string, listener: Listener) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }

      send(raw: string) {
        const frame = JSON.parse(raw) as { type: string; input_epoch?: string };
        if (frame.type === "session_hello") {
          this.message({
            type: "session_ack",
            session_id: "terminate-e2e",
            resumed: false,
            protocol_version: 2,
            resume_token: "terminate-token",
          });
          this.message({
            type: "session_capabilities",
            server_asr: true,
            server_tts: true,
            assistant_text_streaming: true,
            user_transcript_streaming: true,
          });
          this.message({ type: "assistant_text", text: "连接时迟到的回答", generation: 0 });
          return;
        }
        if (frame.type === "input_epoch_started") {
          this.message({
            type: "voice_session_ready",
            session_sequence: 1,
            input_epoch: frame.input_epoch,
          });
          return;
        }
        if (frame.type === "input_audio_frame" && !this.replied) {
          this.replied = true;
          this.message({ type: "assistant_text", text: "上一轮回答", generation: 1 });
          const browserWindow = window as typeof window & {
            __emitLateAssistant: () => void;
          };
          browserWindow.__emitLateAssistant = () => {
            this.message({ type: "assistant_text", text: "迟到回答", generation: 1 });
          };
        }
      }

      close() {
        this.readyState = FakeWebSocket.CLOSED;
      }

      private message(frame: object) {
        this.emit("message", new MessageEvent("message", { data: JSON.stringify(frame) }));
      }

      private emit(type: string, event: Event | MessageEvent<string>) {
        for (const listener of this.listeners.get(type) ?? []) listener(event);
      }
    }

    class FakeAudioContext {
      audioWorklet = { addModule: async () => undefined };

      createMediaStreamSource() {
        return { connect: () => undefined };
      }

      createAnalyser() {
        return {
          fftSize: 0,
          getByteTimeDomainData: (samples: Uint8Array) => samples.fill(128),
        };
      }

      async close() {}
    }

    class FakeAudioWorkletNode {
      private inputEpoch = "";
      port: {
        onmessage: ((event: MessageEvent<unknown>) => void) | null;
        postMessage: (command: { type: string; input_epoch?: string }) => void;
      } = {
        onmessage: null,
        postMessage: (command) => {
          if (command.type === "begin_epoch") this.inputEpoch = command.input_epoch ?? "";
          if (command.type !== "release") return;
          setTimeout(() => {
            this.port.onmessage?.(
              new MessageEvent("message", {
                data: {
                  type: "audio_frame",
                  inputEpoch: this.inputEpoch,
                  captureMode: "prebuffer",
                  pcm16: new ArrayBuffer(1_024),
                },
              }),
            );
          }, 0);
        },
      };
      constructor(_context: unknown, _name: string, options: { processorOptions?: { inputEpoch?: string } }) {
        this.inputEpoch = options.processorOptions?.inputEpoch ?? "";
      }
      connect() {}
      disconnect() {}
    }

    const browserWindow = window as typeof window & {
      WebSocket: typeof WebSocket;
      AudioContext: typeof AudioContext;
      AudioWorkletNode: typeof AudioWorkletNode;
    };
    browserWindow.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    browserWindow.AudioContext = FakeAudioContext as unknown as typeof AudioContext;
    browserWindow.AudioWorkletNode = FakeAudioWorkletNode as unknown as typeof AudioWorkletNode;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async () => ({
          getTracks: () => [{ stop: () => undefined }],
        }),
      },
    });
  });

  await page.goto("/");
  await expect(page.locator(".status-dot")).toHaveText("待命");
  await page.getByRole("button", { name: "开始语音对话" }).click();
  await expect(page.locator(".orb-conversation-status")).toHaveText("AI 回复中");

  await page.getByRole("button", { name: "结束通话" }).click();
  await expect(page.locator(".status-dot")).toHaveText("待命");

  await page.evaluate(() => {
    (window as typeof window & { __emitLateAssistant: () => void })
      .__emitLateAssistant();
  });
  await expect(page.locator(".status-dot")).toHaveText("待命");

  await page.getByRole("button", { name: "开始语音对话" }).click();
  await expect(page.locator(".orb-conversation-status")).toHaveText("正在听");
});

test("browser speech permission denial exits listening instead of retrying forever", async ({ page }) => {
  await page.addInitScript(() => {
    type Listener = (event: Event | MessageEvent<string>) => void;

    class FakeWebSocket {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSING = 2;
      static readonly CLOSED = 3;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSING = 2;
      readonly CLOSED = 3;
      readyState = FakeWebSocket.CONNECTING;
      private listeners = new Map<string, Listener[]>();

      constructor() {
        setTimeout(() => {
          this.readyState = FakeWebSocket.OPEN;
          this.emit("open", new Event("open"));
        }, 0);
      }

      addEventListener(type: string, listener: Listener) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }

      send(raw: string) {
        const frame = JSON.parse(raw) as { type: string };
        if (frame.type !== "session_hello") return;
        this.message({ type: "session_ack", session_id: "denied", resumed: false });
        this.message({
          type: "session_capabilities",
          server_asr: false,
          server_tts: false,
          assistant_text_streaming: true,
          user_transcript_streaming: false,
        });
      }

      close() {
        this.readyState = FakeWebSocket.CLOSED;
      }

      private message(frame: object) {
        this.emit("message", new MessageEvent("message", { data: JSON.stringify(frame) }));
      }

      private emit(type: string, event: Event | MessageEvent<string>) {
        for (const listener of this.listeners.get(type) ?? []) listener(event);
      }
    }

    class DeniedSpeechRecognition {
      continuous = true;
      interimResults = true;
      lang = "zh-CN";
      onresult = null;
      onerror: ((event: { error: string }) => void) | null = null;
      onend: (() => void) | null = null;

      start() {
        setTimeout(() => this.onerror?.({ error: "not-allowed" }), 20);
      }

      stop() {}
      abort() {}
    }

    const browserWindow = window as typeof window & {
      WebSocket: typeof WebSocket;
      SpeechRecognition: typeof DeniedSpeechRecognition;
      webkitSpeechRecognition: typeof DeniedSpeechRecognition;
    };
    browserWindow.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    browserWindow.SpeechRecognition = DeniedSpeechRecognition;
    browserWindow.webkitSpeechRecognition = DeniedSpeechRecognition;
  });

  await page.goto("/");
  const mic = page.getByRole("button", { name: "开始语音对话" });
  await expect(mic).toBeEnabled();
  await mic.click();

  await expect(page.locator(".status-dot")).toHaveText("待命");
  await expect(page.locator(".current-turn-text")).toContainText(
    "当前浏览器拒绝语音识别",
  );
});

test("live demo keeps two simulated speakers as separate turns", async ({ page }) => {
  test.skip(
    !process.env.VOICEAGENT_E2E_LIVE,
    "requires the local OpenRealtime WebSocket backend",
  );
  await page.addInitScript(() => {
    window.speechSynthesis.speak = (utterance: SpeechSynthesisUtterance) => {
      utterance.dispatchEvent(new Event("end"));
    };
  });
  await page.goto("/");
  await page.getByRole("button", { name: "开始语音对话" }).click();
  await enterContentPageForm(page);
  const input = page.getByRole("textbox", { name: "输入对话消息" });

  await input.fill("张三：你好，我先发言");
  await input.press("Enter");
  await expect(page.locator(".bubble--user")).toHaveCount(1);
  await expect(page.locator(".bubble--user").first()).toContainText(
    "张三：你好，我先发言",
  );
  await expect(page.locator(".bubble--assistant")).toHaveCount(1);
  await expect(page.locator(".bubble--assistant").first()).toHaveAttribute(
    "data-status",
    "completed",
  );
  await expect(page.locator(".bubble--assistant").first()).toContainText(/\S/);
  await expect(page.locator(".status-dot")).toHaveAttribute(
    "data-state",
    "listening",
  );

  await input.fill("李四：收到，现在轮到我");
  await input.press("Enter");
  await expect(page.locator(".bubble--user")).toHaveCount(2);
  await expect(page.locator(".bubble--user").last()).toContainText(
    "李四：收到，现在轮到我",
  );
  await expect(page.locator(".bubble--assistant")).toHaveCount(2);
  await expect(page.locator(".bubble--assistant").last()).toHaveAttribute(
    "data-status",
    "completed",
  );
  await expect(page.locator(".bubble--assistant").last()).toContainText(/\S/);
});
