import { createHash } from "node:crypto";
import { writeFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { issueDiagnosticsAccess } from "../src/lib/diagnostics-access";

type Frame = Record<string, unknown>;
type RendererEvidence = { receipts: Frame[]; audio: Frame[]; commands: Frame[]; stopResults: Frame[]; stoppedSources: number; starts: { when: number; duration: number; first: number; uniform: boolean }[] };
declare global { interface Window { __recordingRenderer: RendererEvidence } }

const sessionId = "recording-browser-session";
const scenario = process.env.RECORDING_BROWSER_SCENARIO ?? "normal";
const chunkSamples = scenario === "normal" ? 3200 : 32000;
const totalSamples = chunkSamples * 2;
const root = `/api/observability/sessions/${sessionId}/recordings`;

test(`production WebAudio ${scenario} receipts join actual sent WAV and stop diagnostics`, async ({ page, context, request, playwright, baseURL }, info) => {
  test.skip(process.env.RUN_RECORDING_BROWSER_INTEGRATION !== "1" || process.env.RECORDING_BROWSER_RENDERER !== "1",
    "requires the owned isolated Runtime/PG renderer fixture");
  test.setTimeout(90_000);
  if (!["normal", "stop", "missing", "disconnect"].includes(scenario)) throw new Error("unknown recording scenario");
  const port = Number(process.env.RECORDING_BROWSER_RENDERER_PORT);
  if (!baseURL || new URL(baseURL).hostname !== "127.0.0.1" || new URL(baseURL).port !== "3029"
    || !/^voiceagent_recording_browser_[a-f0-9]{32}$/.test(process.env.VOICEAGENT_POSTGRES_SCHEMA ?? "")
    || !Number.isInteger(port) || port < 1 || port > 65535) throw new Error("isolated renderer fixture required");
  const fixture = `http://127.0.0.1:${port}`;
  const pageErrors: string[] = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  await page.addInitScript(({ port, scenario }) => {
    if (!/^https?:$/.test(location.protocol)) return;
    localStorage.setItem("openrealtime-language", "zh-CN");
    const evidence: RendererEvidence = { receipts: [], audio: [], commands: [], stopResults: [], stoppedSources: 0, starts: [] };
    window.__recordingRenderer = evidence;
    const Original = window.WebSocket;
    window.WebSocket = new Proxy(Original, { construct(target, args) {
      const url = new URL(String(args[0]), location.href);
      if (url.port !== "8765" && url.pathname !== "/voice") return Reflect.construct(target, args);
      const socket = new target(`ws://127.0.0.1:${port}/voice`);
      const send = socket.send.bind(socket);
      socket.send = raw => {
        const frame = JSON.parse(String(raw)) as Frame;
        if (frame.type === "playback_progress_v2") evidence.receipts.push(frame);
        if (frame.type === "output_stop_result") {
          evidence.stopResults.push(frame);
          // Real renderer stops and produces the real receipt; only its wire
          // delivery is lost in these explicitly controlled fault cases.
          if (scenario === "missing" || scenario === "disconnect") return;
        }
        send(raw);
      };
      socket.addEventListener("message", event => {
        const frame = JSON.parse(String(event.data)) as Frame;
        if (frame.type === "assistant_audio_chunk") evidence.audio.push(frame);
        if (frame.type === "assistant_speech_cancelled") evidence.commands.push(frame);
      });
      return socket;
    } });
    window.AudioContext = new Proxy(window.AudioContext, { construct(target, args) {
      const audio = Reflect.construct(target, args) as AudioContext;
      const create = audio.createBufferSource.bind(audio);
      audio.createBufferSource = () => {
        const source = create(), start = source.start.bind(source), stop = source.stop.bind(source);
        source.stop = when => { evidence.stoppedSources++; stop(when); };
        source.start = when => {
          const samples = source.buffer?.getChannelData(0);
          evidence.starts.push({ when: when ?? 0, duration: source.buffer?.duration ?? 0,
            first: samples?.[0] ?? 0, uniform: samples?.every(value => value === samples[0]) ?? false });
          start(when);
        };
        return source;
      };
      return audio;
    } });
    class Recognition { continuous = true; interimResults = true; lang = "zh-CN"; start() {} stop() {} abort() {} }
    Object.assign(window, { SpeechRecognition: Recognition, webkitSpeechRecognition: Recognition });
  }, { port, scenario });
  let browser: RendererEvidence | null = null;
  let catalog: unknown = null;
  let diagnosticEvidence: unknown = null;
  let hasPrimaryError = false;
  try {
    await page.goto("/conversation?role_id=e2e-unassigned");
    await page.getByRole("button", { name: "主页开始对话" }).click();
    await expect(page.getByRole("button", { name: "关闭麦克风" })).toBeVisible();
    await expect.poll(async () => (await (await request.get(`${fixture}/evidence`, { timeout: 2000 })).json()).ready).toBe(true);
    expect((await request.get(`${fixture}/start`, { timeout: 2000 })).status()).toBe(200);
    let expectedEndSample = totalSamples;
    if (scenario === "normal") {
      await expect.poll(() => page.evaluate(() => window.__recordingRenderer.receipts.some(frame =>
        frame.phase === "finished" && frame.played_position_samples === 6400)), { timeout: 5000 }).toBe(true);
      await expect.poll(async () => (await (await request.get(`${fixture}/evidence`, { timeout: 2000 })).json()).canonical.some(
        (frame: Frame) => frame.completed === true && frame.played_position_samples === 6400)).toBe(true);
    } else {
      await expect.poll(() => page.evaluate(() => window.__recordingRenderer.receipts.some(frame =>
        frame.phase === "playing" && Number(frame.played_position_samples) > 0)), { intervals: [20], timeout: 3000 }).toBe(true);
      expect((await request.get(`${fixture}/stop`, { timeout: 2000 })).status()).toBe(200);
      await expect.poll(() => page.evaluate(() => window.__recordingRenderer.stopResults.length), { intervals: [20], timeout: 3000 }).toBe(1);
      const result = await page.evaluate(() => window.__recordingRenderer.stopResults[0]);
      expect(result).toMatchObject({ outcome: "queue_stopped", output_epoch: "fixture-renderer-output",
        speech_id: "fixture-speech", generation: 0 });
      expect(Number(result.played_position_samples)).toBeGreaterThan(0);
      expect(Number(result.played_position_samples)).toBeLessThan(totalSamples);
      await expect.poll(() => page.evaluate(() => window.__recordingRenderer.stoppedSources)).toBeGreaterThanOrEqual(2);
      if (scenario === "disconnect") expect((await request.get(`${fixture}/disconnect`, { timeout: 2000 })).status()).toBe(200);
      if (scenario === "stop") {
        await expect.poll(async () => (await (await request.get(`${fixture}/evidence`, { timeout: 2000 })).json()).canonical.some(
          (frame: Frame) => frame.stopped === true && frame.played_position_samples === result.played_position_samples)).toBe(true);
        expectedEndSample = Number(result.played_position_samples);
      } else {
        await expect.poll(async () => (await (await request.get(`${fixture}/evidence`, { timeout: 2000 })).json()).stop_observations.some(
          (frame: Frame) => frame.state === "STOP_UNKNOWN" && frame.reason === (scenario === "missing" ? "receipt_deadline" : "transport_detached"))).toBe(true);
        const backend = await (await request.get(`${fixture}/evidence`, { timeout: 2000 })).json();
        expect(backend.canonical.some((frame: Frame) => frame.stopped || frame.completed)).toBe(false);
        expectedEndSample = Math.max(0, ...backend.canonical.map((frame: Frame) => Number(frame.played_position_samples ?? 0)));
        expect(expectedEndSample).toBeGreaterThan(0);
        expect(expectedEndSample).toBeLessThanOrEqual(Number(result.played_position_samples));
        if (scenario === "missing") await expect(page.getByText("无法确认音频已经停止，请重新打开页面后开始会话。").first()).toBeVisible();
      }
      expect((await request.get(`${fixture}/late`, { timeout: 2000 })).status()).toBe(200);
      expect(await page.evaluate(() => window.__recordingRenderer.receipts.some(frame => frame.phase === "finished"))).toBe(false);
    }
    browser = await page.evaluate(() => window.__recordingRenderer);
    expect(browser.audio).toHaveLength(scenario === "normal" ? 3 : 2);
    expect(browser.audio.every(frame => frame.speech_id === "fixture-speech" && frame.generation === 0 && frame.sample_rate_hz === 16000)).toBe(true);
    expect(browser.audio.map(frame => frame.is_final)).toEqual(scenario === "normal" ? [false, false, true] : [false, false]);
    const starts = browser.starts.filter(source => source.duration > 1 / 16000);
    expect(starts).toHaveLength(2);
    expect(starts.map(source => source.duration)).toEqual([chunkSamples / 16000, chunkSamples / 16000]);
    expect(starts.map(source => source.first)).toEqual([1000 / 32768, -1000 / 32768]);
    expect(starts.every(source => source.uniform)).toBe(true);
    expect(starts[1].when).toBeCloseTo(starts[0].when + chunkSamples / 16000, 5);
    expect(browser.receipts.every(frame => frame.output_epoch === "fixture-renderer-output"
      && frame.speech_id === "fixture-speech" && frame.generation === 0
      && Number.isInteger(frame.played_position_samples) && Number(frame.played_position_samples) <= totalSamples)).toBe(true);

    // Leaving the conversation closes the actual Bridge and settles its sent
    // recording. The receipt used below was generated by this production page.
    await context.addCookies([{ name: "openrealtime_user_session", value: "recording-test-only-cookie-token-0000000000000", url: baseURL, httpOnly: true, sameSite: "Lax" }]);
    await page.goto(`/settings/session-diagnostics/sessions/${sessionId}`);
    await expect.poll(async () => (await (await request.get(`${fixture}/evidence`, { timeout: 2000 })).json()).closed).toBe(true);
    const settled = await (await request.get(`${fixture}/evidence`, { timeout: 2000 })).json();
    if (scenario !== "normal") {
      expect(settled.stop_observations.length).toBeGreaterThan(0);
      expect(new Set(settled.stop_observations.map((event: Frame) => event.stop_command_id)).size).toBe(1);
      for (const event of settled.stop_observations as Frame[]) {
        expect(event.saved_state).toBe(scenario === "stop" ? "STOP_CONFIRMED" : "STOP_UNKNOWN");
        expect(event.saved_position_samples).toBe(scenario === "stop" ? expectedEndSample : null);
      }
    }
    const panel = page.getByRole("region", { name: "会话录音" });
    await panel.getByRole("button", { name: "查看录音" }).click();
    const covered = panel.getByText(`回执覆盖 ${(expectedEndSample / 16000).toFixed(3)} / ${(totalSamples / 16000).toFixed(3)} 秒`);
    await expect(covered).toBeVisible();
    await expect(covered).toHaveAttribute("title", new RegExp(`${expectedEndSample} / ${totalSamples} 个采样点.*不证明扬声器实际播出或用户听到`));

    const grant = issueDiagnosticsAccess(sessionId, "isolated-renderer-agent", process.env.OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET);
    const authorization = `Bearer ${grant.access_token}`;
    const anonymous = await playwright.request.newContext({ baseURL });
    try {
      const response = await anonymous.get(root, { headers: { Authorization: authorization } });
      expect(response.status()).toBe(200);
      const data = await response.json();
      catalog = data;
      expect(data.playback_source).toMatchObject({ status: "available", truncated: false });
      const rows = data.items.filter((item: Frame) => item.direction === "sent");
      expect(rows).toHaveLength(1);
      const row = rows[0];
      expect(row).toMatchObject({ epoch: "fixture-renderer-output", speech_id: "fixture-speech",
        stream_id: "fixture-speech", generation: 0, start_sample: 0, sample_count: totalSamples,
        playback_confirmation: "not-inferred", playback: { status: "reported", reported_end_sample: expectedEndSample,
          overlap_samples: expectedEndSample, sample_rate_hz: 16000 } });
      const wav = await anonymous.get(row.audio_url, { headers: { Authorization: authorization } });
      expect(wav.status()).toBe(200);
      const bytes = await wav.body();
      expect(bytes.length).toBe(totalSamples * 2 + 44);
      expect(bytes.length).toBe(row.size_bytes);
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(row.sha256);
      expect(bytes.subarray(0, 4).toString()).toBe("RIFF");
      expect(bytes.readUInt32LE(24)).toBe(16000);
      const expectedPcm = Buffer.alloc(totalSamples * 2);
      for (let index = 0; index < totalSamples; index++) expectedPcm.writeInt16LE(index < chunkSamples ? 1000 : -1000, index * 2);
      expect(bytes.subarray(44).equals(expectedPcm)).toBe(true);
      const wirePcm = Buffer.concat(browser.audio.map(frame => Buffer.from(String(frame.pcm16_base64), "base64")));
      expect(bytes.subarray(44).equals(wirePcm)).toBe(true);
      const diagnosticResponse = await anonymous.get(`/api/observability/sessions/${sessionId}/diagnostics`,
        { headers: { Authorization: authorization }, timeout: 15000 });
      expect(diagnosticResponse.status()).toBe(200);
      const diagnostics = await diagnosticResponse.json();
      diagnosticEvidence = diagnostics;
      expect(diagnostics.sources.telemetry.status).toBe("available");
      expect(diagnostics.collection_health).toBeNull();
      if (scenario !== "normal") {
        const events = diagnostics.telemetry.events as Frame[];
        expect(events.filter(event => event.name === "playback.stop_requested")).toHaveLength(1);
        if (scenario === "stop") {
          expect(events.filter(event => event.name === "playback.stop_receipt")).toHaveLength(1);
          const span = events.find(event => event.name === "playback.stop_request_to_receipt");
          expect(span).toMatchObject({ outcome: "ok", kind: "span" });
          expect(Number(span?.duration_ms)).toBeGreaterThanOrEqual(0);
          expect(events.some(event => event.name === "playback.stop_handoff_failed")).toBe(false);
        } else {
          expect(events.some(event => event.name === "playback.stop_receipt")).toBe(false);
          const failure = events.find(event => event.name === "playback.stop_handoff_failed");
          expect(failure).toMatchObject({ outcome: scenario === "missing" ? "timeout" : "error" });
          expect(events.some(event => event.name === "playback.stop_request_to_receipt")).toBe(false);
        }
      }
      expect((await anonymous.post(`${root}/preservation`, { headers: { Authorization: authorization, Origin: baseURL } })).status()).toBe(403);
    } finally { await anonymous.dispose(); }
    expect(pageErrors).toEqual([]);
  } catch (error) {
    hasPrimaryError = true;
    throw error;
  } finally {
    const cleanupErrors: string[] = [];
    const capture = (error: unknown) => { cleanupErrors.push(String(error)); };
    // Retain the primary assertion failure if shutdown or evidence collection
    // also fails; every network operation here has its own short deadline.
    if (!page.isClosed()) {
      if (browser === null) browser = await page.evaluate(() => window.__recordingRenderer).catch(() => null);
      await page.goto("about:blank", { timeout: 5000 }).catch(capture);
    }
    await expect.poll(async () => (await (await request.get(`${fixture}/evidence`, { timeout: 2000 })).json()).closed,
      { timeout: 5000 }).toBe(true).catch(capture);
    const backend = await request.get(`${fixture}/evidence`, { timeout: 2000 })
      .then(response => response.json()).catch(error => { capture(error); return null; });
    if (backend?.error) capture(backend.error);
    const artifact = info.outputPath("recording-renderer.json");
    await writeFile(artifact, JSON.stringify({ browser, backend, catalog, diagnostics: diagnosticEvidence, pageErrors, cleanupErrors }, null, 2)).catch(capture);
    await info.attach("recording-renderer", { path: artifact, contentType: "application/json" }).catch(capture);
    if (!hasPrimaryError && cleanupErrors.length > 0) throw new Error(cleanupErrors.join("\n"));
  }
});
