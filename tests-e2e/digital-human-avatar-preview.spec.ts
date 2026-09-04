import { expect, test } from "@playwright/test";

const REMOTE_AVATAR_PREVIEW =
  "https://newgxnc1uqs0jnqm.public.blob.vercel-storage.com/avatar-previews/oF0ubkPo7fSzdMoGJpMSXaT2cxSVr2_N/one-shot_oF0ubkPo7fSzdMoGJpMSXaT2cxSVr2_N_thinkres-digital-twin1787325233514-cropped-FgaBhvzV7gk2KWNypH6AwFqIoCIBzE.png";
const REMOTE_STOCK_AVATAR =
  "https://newgxnc1uqs0jnqm.public.blob.vercel-storage.com/avatars/stock/mia_studio.webp";

test("activating digital-human mode exposes its avatar workspace", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("voice-agent-avatar-display-config", JSON.stringify({
      renderPath: "segmented",
      provider: "anam",
      avatarProfileId: "default-anam",
      segmentedAvatarId: "custom-upload",
      segmentedVisualIdentityId: "companion",
      segmentedVideoId: "liveportrait-optimized",
      segmentedMotionBaseId: "builtin:opentalking:companion",
      segmentedLipSyncId: "wav2lip96",
      surface: "fullbleed",
      framing: "half",
      ratio: "16:9",
      quality: "quality",
      fallbackToClassic: true,
    }));
  });
  await page.route("**/api/anam/avatars", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [] }) });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "数字人", exact: true }).click();
  await page.getByRole("button", { name: "展开会话配置工作台" }).click();

  await expect(page.getByRole("heading", { name: "选择与你对话的数字人" })).toHaveCount(0);
  await expect(page.getByRole("group", { name: "数字人驱动方式" })).toBeVisible();
  await page.getByRole("button", { name: /多段式合成/ }).click();
  await expect(page.getByRole("heading", { name: "本机口型模型" })).toBeVisible();
  await expect(page.getByRole("radio", { name: /Wav2Lip 96/ })).toBeEnabled();
  await expect(page.getByRole("radio", { name: /Wav2Lip 96/ })).toBeChecked();
  await expect(page.getByText("DH_live_mini v1")).toHaveCount(0);
  await expect(page.getByText("LiteAvatar")).toHaveCount(0);
  await expect(page.getByText("FeatherTalk")).toHaveCount(0);
});

test("browsing an Avatar action does not change the session configuration until confirmed", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("voice-agent-experience-mode", "avatar");
    localStorage.setItem("voice-agent-avatar-display-config", JSON.stringify({
      renderPath: "segmented",
      provider: "anam",
      avatarProfileId: "default-anam",
      segmentedPresetId: "custom-upload",
      segmentedAvatarId: "companion",
      segmentedDisplayName: "陪伴",
      segmentedVideoId: "liveportrait-optimized",
      segmentedAvatarActionId: "",
      segmentedLipSyncId: "wav2lip96",
      surface: "fullbleed",
      framing: "half",
      ratio: "16:9",
      quality: "quality",
      fallbackToClassic: true,
    }));
  });
  await page.route("**/api/anam/avatars", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [] }) });
  });
  await page.route("**/api/avatars", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        avatars: [{
          avatar_id: "private-avatar",
          display_name: "用户自定义 Avatar",
          source_image_url: "/digital-human/shuchang-preview.jpg",
          owner_id: "local-user",
          visibility: "private",
          created_at: "2026-08-29T00:00:00.000Z",
          updated_at: "2026-08-29T00:00:00.000Z",
          deleted_at: null,
          realtime_binding: null,
          actions: [],
        }],
      }),
    });
  });
  await page.route("**/api/avatar-assets/actions", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ actions: [], selection: null }) });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "展开会话配置工作台" }).click();
  await page.getByRole("button", { name: /多段式合成/ }).click();

  await expect(page.getByText("内置 Avatar", { exact: true })).toBeVisible();
  await expect(page.getByText("2 个形象", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /自定义/ })).toHaveCount(0);
  await expect(page.getByRole("article")).toHaveCount(2);
  const card = page.getByRole("article", { name: "陪伴 形象与动作" });
  const workbench = page.getByRole("region", { name: "会话配置工作台" });
  const avatarCards = page.getByRole("article");
  await expect(workbench).toHaveAttribute("data-state", "compact");
  await expect(avatarCards.nth(1)).toHaveAttribute("aria-label", "陪伴 形象与动作");
  await card.getByRole("button", { name: "展开 陪伴 的形象和动作" }).click();
  await expect(workbench).toHaveAttribute("data-state", "compact");
  await expect(card).toHaveAttribute("data-focused", "true");
  const layerBrowser = card.getByRole("group", { name: "陪伴 形象与动作层叠浏览" });
  await expect(layerBrowser).toBeVisible();
  await expect(layerBrowser.getByRole("button", { name: "预览 陪伴 形象" })).toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("article", { name: "Shuchang 形象与动作" })).toBeHidden();
  await expect(card.getByText("当前预览：形象 · 陪伴")).toBeVisible();
  await expect(card).toHaveAttribute("data-selected", "true");
  await card.getByRole("button", { name: "浏览 陪伴 的下一个媒体" }).click();

  await expect(layerBrowser.getByRole("button", { name: "预览动作：陪伴 · 内置动作" })).toHaveAttribute("aria-current", "true");
  await expect(layerBrowser.locator("video[autoplay]")).toHaveCount(1);
  await expect(card).toHaveAttribute("data-selected", "false");
  await expect(card.getByText("当前预览：动作 · 陪伴 · 内置动作")).toBeVisible();
  await expect(card.getByRole("button", { name: "使用动作：陪伴 · 内置动作", exact: true })).toBeEnabled();
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("voice-agent-avatar-display-config") || "{}") as { segmentedAvatarActionId?: string })).toMatchObject({
    segmentedAvatarActionId: "",
  });

  await card.getByRole("button", { name: "使用动作：陪伴 · 内置动作", exact: true }).click();
  await expect(card).toHaveAttribute("data-selected", "true");
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("voice-agent-avatar-display-config") || "{}") as { segmentedAvatarActionId?: string }))
    .toMatchObject({ segmentedAvatarActionId: "builtin:opentalking:companion" });
});

test("can switch back to Shuchang realtime idle after selecting another built-in action", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("voice-agent-experience-mode", "avatar");
    localStorage.setItem("voice-agent-avatar-display-config", JSON.stringify({
      renderPath: "segmented",
      provider: "anam",
      avatarProfileId: "default-anam",
      segmentedPresetId: "custom-upload",
      segmentedAvatarId: "companion",
      segmentedDisplayName: "陪伴",
      segmentedVideoId: "liveportrait-optimized",
      segmentedAvatarActionId: "builtin:opentalking:companion",
      segmentedLipSyncId: "wav2lip96",
      surface: "fullbleed",
      framing: "half",
      ratio: "16:9",
      quality: "quality",
      fallbackToClassic: true,
    }));
  });
  await page.route("**/api/anam/avatars", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [] }) });
  });
  await page.route("**/api/avatars", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [] }) });
  });
  await page.route("**/api/avatar-assets/actions", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ actions: [], selection: null }) });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "展开会话配置工作台" }).click();
  await page.getByRole("button", { name: /多段式合成/ }).click();

  const shuchangCard = page.getByRole("article", { name: "Shuchang 形象与动作" });
  await shuchangCard.getByRole("button", { name: "展开 Shuchang 的形象和动作" }).click();
  await shuchangCard.getByRole("button", { name: "浏览 Shuchang 的下一个媒体" }).click();
  await expect(shuchangCard.getByRole("button", { name: "使用动作：实时待机" })).toBeEnabled();
  await shuchangCard.getByRole("button", { name: "使用动作：实时待机" }).click();

  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("voice-agent-avatar-display-config") || "{}") as {
    segmentedAvatarId?: string;
    segmentedAvatarActionId?: string;
  })).toMatchObject({
    segmentedAvatarId: "shuchang",
    segmentedAvatarActionId: "builtin:shuchang-realtime-idle",
  });
});

test("digital-human workspace accepts hosted avatar preview images", async ({ page }) => {
  const runtimeErrors: string[] = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));

  await page.route("**/api/anam/avatars", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        avatars: [
          {
            id: "remote-avatar",
            displayName: "Remote Avatar",
            imageUrl: REMOTE_AVATAR_PREVIEW,
            origin: "personal",
          },
          {
            id: "stock-avatar",
            displayName: "Mia",
            imageUrl: REMOTE_STOCK_AVATAR,
            origin: "platform",
          },
        ],
      }),
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "数字人", exact: true }).click();
  await page.getByRole("button", { name: "展开会话配置工作台" }).click();

  await expect.poll(async () => ({
    runtimeError: runtimeErrors.find((message) => message.includes("Invalid src prop")) ?? "",
    ready: await page.getByText("Remote Avatar").isVisible(),
  })).toEqual({ runtimeError: "", ready: true });
  await expect(page.getByText("Remote Avatar")).toBeVisible();
  await expect(page.getByText("Mia")).toBeVisible();

  await page.getByRole("button", { name: "Remote Avatar 自定义数字人" }).click();
  await expect(page.getByAltText("Remote Avatar 数字人预览")).toBeVisible();
  await expect(page.getByText(/你好，我是/)).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("voice-agent-avatar-display-config") || "{}") as { avatarProfileId?: string }))
    .toMatchObject({ avatarProfileId: "remote-avatar" });

  await expect(page.getByRole("button", { name: "Remote Avatar 自定义数字人 · 当前使用" })).toBeVisible();
});

test("prepared segmented avatar starts a moving lip-sync renderer and receives TTS audio", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("voice-agent-experience-mode", "avatar");
    localStorage.setItem("voice-agent-avatar-display-config", JSON.stringify({
      renderPath: "segmented",
      provider: "anam",
      avatarProfileId: "default-anam",
      segmentedAvatarId: "shuchang",
      segmentedVisualIdentityId: "shuchang",
      segmentedVideoId: "liveportrait-optimized",
      segmentedMotionBaseId: "builtin:liveportrait-optimized",
      segmentedLipSyncId: "wav2lip96",
      surface: "fullbleed",
      framing: "half",
      ratio: "16:9",
      quality: "quality",
      fallbackToClassic: true,
    }));
    type Listener = (event: Event | MessageEvent<string>) => void;
    class FakeWebSocket {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSING = 2;
      static readonly CLOSED = 3;
      static activeSocket: FakeWebSocket | null = null;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSING = 2;
      readonly CLOSED = 3;
      readyState = FakeWebSocket.CONNECTING;
      private listeners = new Map<string, Listener[]>();

      constructor(url: string) {
        if (url.includes(":8765")) FakeWebSocket.activeSocket = this;
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
        this.message({ type: "session_ack", session_id: "segmented-e2e", resumed: false });
        this.message({
          type: "session_capabilities",
          server_asr: false,
          server_tts: true,
          assistant_text_streaming: true,
          user_transcript_streaming: false,
        });
      }

      close() {
        this.readyState = FakeWebSocket.CLOSED;
      }

      message(frame: object) {
        this.emit("message", new MessageEvent("message", { data: JSON.stringify(frame) }));
      }

      private emit(type: string, event: Event | MessageEvent<string>) {
        for (const listener of this.listeners.get(type) ?? []) listener(event);
      }
    }

    class FakeSpeechRecognition {
      continuous = true;
      interimResults = true;
      lang = "zh-CN";
      onresult = null;
      onerror = null;
      onend = null;
      start() {}
      stop() {}
      abort() {}
    }

    type PeerListener = (event: { track?: MediaStreamTrack }) => void;
    class FakeRTCPeerConnection {
      iceGatheringState = "complete";
      connectionState = "new";
      localDescription: RTCSessionDescriptionInit | null = null;
      private listeners = new Map<string, PeerListener[]>();

      addTransceiver() {}
      createOffer() {
        return Promise.resolve({ type: "offer" as RTCSdpType, sdp: "fake-offer" });
      }
      setLocalDescription(description: RTCSessionDescriptionInit) {
        this.localDescription = description;
        return Promise.resolve();
      }
      setRemoteDescription() {
        const canvas = document.createElement("canvas");
        const track = canvas.captureStream(1).getVideoTracks()[0]!;
        for (const listener of this.listeners.get("track") ?? []) listener({ track });
        this.connectionState = "connected";
        for (const listener of this.listeners.get("connectionstatechange") ?? []) listener({});
        return Promise.resolve();
      }
      addEventListener(type: string, listener: PeerListener) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }
      removeEventListener(type: string, listener: PeerListener) {
        this.listeners.set(type, (this.listeners.get(type) ?? []).filter((item) => item !== listener));
      }
      close() {
        this.connectionState = "closed";
      }
    }

    const browserWindow = window as typeof window & {
      WebSocket: typeof WebSocket;
      RTCPeerConnection: typeof RTCPeerConnection;
      SpeechRecognition: typeof FakeSpeechRecognition;
      webkitSpeechRecognition: typeof FakeSpeechRecognition;
      emitAvatarAudio: () => void;
    };
    browserWindow.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    browserWindow.RTCPeerConnection = FakeRTCPeerConnection as unknown as typeof RTCPeerConnection;
    browserWindow.SpeechRecognition = FakeSpeechRecognition;
    browserWindow.webkitSpeechRecognition = FakeSpeechRecognition;
    browserWindow.emitAvatarAudio = () => FakeWebSocket.activeSocket?.message({
      type: "assistant_audio",
      generation: 1,
      pcm16_base64: "AAAAAAAAAAA=",
      sample_rate_hz: 24_000,
    });
  });
  await page.route("**/api/anam/avatars", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [] }) });
  });
  await page.route("**/api/avatar-renderer/session", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        endpoint: "http://127.0.0.1:8010",
        avatar_id: "shuchang",
        model: "wav2lip96",
      }),
    });
  });
  await page.route("**/api/avatar-renderer/preparations", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "ready", progress: 100, avatarId: "shuchang" }),
    });
  });
  await page.route("http://127.0.0.1:8010/offer", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ sdp: "fake-answer", type: "answer", sessionid: "wav2lip-e2e" }),
    });
  });
  let receivedWav2LipAudio = false;
  await page.route("http://127.0.0.1:8010/humanaudio", async (route) => {
    receivedWav2LipAudio = true;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ code: 0 }) });
  });

  await page.goto("/");
  const start = page.getByRole("button", { name: "主页开始对话" });
  await expect(start).toBeEnabled();
  await expect(page.getByText("与 Shuchang 对话")).toBeVisible();
  await start.click();

  await expect(page.locator('.digital-human-call-stage[data-render-path="segmented"]')).toBeVisible();
  await expect(page.locator('.digital-human-call-stage[data-renderer-state="ready"]')).toBeVisible();
  await expect(page.getByLabel("Wav2Lip 实时数字人画面")).toBeVisible();
  await expect(page.getByRole("button", { name: "结束通话" })).toBeVisible();
  expect(await page.evaluate(() => typeof window.AudioContext)).toBe("function");
  await page.evaluate(() => (window as typeof window & { emitAvatarAudio: () => void }).emitAvatarAudio());
  await expect(page.locator('.digital-human-call-stage[data-state="speaking"]')).toBeVisible();
  await expect.poll(() => receivedWav2LipAudio).toBe(true);
});
