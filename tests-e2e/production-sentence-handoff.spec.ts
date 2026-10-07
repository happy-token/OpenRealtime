import { spawn, type ChildProcess } from "node:child_process";
import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

type Frame = Record<string, unknown>;
type Evidence = { sent: { frame: Frame; clock: number }[]; received: { frame: Frame; clock: number }[];
  sources: { action: string; clock: number; when?: number; duration?: number }[] };
declare global { interface Window { __productionHandoff: Evidence } }

let fixture: ChildProcess;
let port: number;
let fixtureErrors = "";

test.beforeAll(async () => {
  fixture = spawn(process.env.OPENREALTIME_TEST_PYTHON ?? resolve(".venv/bin/python"), ["-m", "tests.browser_sentence_handoff_fixture"], {
    stdio: ["ignore", "pipe", "pipe"],
  });
  fixture.stderr!.on("data", (data: Buffer) => { fixtureErrors = (fixtureErrors + data.toString()).slice(-8192); });
  port = await new Promise<number>((resolve, reject) => {
    let output = "";
    const deadline = setTimeout(() => reject(new Error(`fixture not ready: ${fixtureErrors}`)), 10000);
    fixture.once("exit", code => { clearTimeout(deadline); reject(new Error(`fixture exit ${code}: ${fixtureErrors}`)); });
    fixture.stdout!.on("data", (data: Buffer) => {
      output += data.toString();
      if (output.includes("\n")) {
        clearTimeout(deadline);
        resolve((JSON.parse(output.split("\n")[0]) as { port: number }).port);
      }
    });
  });
});

test.afterAll(async () => {
  if (!fixture) return;
  let forced = false;
  if (fixture.exitCode === null) {
    const exited = new Promise<void>(resolve => fixture.once("exit", () => resolve()));
    const deadline = setTimeout(() => { forced = true; fixture.kill("SIGKILL"); }, 5000);
    try {
      fixture.kill("SIGTERM");
      await exited;
    } finally {
      clearTimeout(deadline);
    }
  }
  expect(forced, `fixture required forced cleanup: ${fixtureErrors}`).toBe(false);
  expect(fixture.exitCode, fixtureErrors).toBe(0);
});

test.afterEach(async ({ page, request }, info) => {
  await page.close();
  try {
    await expect.poll(async () => (await (await request.get(`http://127.0.0.1:${port}/evidence`,
      { timeout: 2000 })).json()).closed, { timeout: 5000 }).toBe(true);
  } finally {
    const backend = await request.get(`http://127.0.0.1:${port}/evidence`, { timeout: 2000 })
      .then(response => response.json()).catch((error: Error) => ({ evidence_error: error.message }));
    const artifact = info.outputPath("fixture-shutdown.json");
    await writeFile(artifact, JSON.stringify({ backend, fixtureErrors }, null, 2));
    await info.attach("fixture-shutdown", { path: artifact, contentType: "application/json" });
  }
});

for (const kind of ["text", "speech"] as const) {
  for (const scenario of ["normal", "revoked_pending"] as const) {
    test(`actual socket and WebAudio handle ${kind} ${scenario} at the permitted sentence end`, async ({ page, request }, info) => {
      const pageErrors: string[] = [];
      page.on("pageerror", error => pageErrors.push(error.stack ?? error.message));
      await page.addInitScript(({ port, kind, scenario }) => {
        localStorage.setItem("openrealtime-language", "zh-CN");
        const evidence: Evidence = { sent: [], received: [], sources: [] };
        window.__productionHandoff = evidence;
        const Original = window.WebSocket;
        window.WebSocket = new Proxy(Original, { construct(target, args) {
          const url = new URL(String(args[0]), location.href);
          if (url.port !== "8765" && url.pathname !== "/voice") return Reflect.construct(target, args);
          const socket = new target(`ws://127.0.0.1:${port}/voice?kind=${kind}&scenario=${scenario}`);
          const send = socket.send.bind(socket);
          socket.send = raw => {
            evidence.sent.push({ frame: JSON.parse(String(raw)) as Frame, clock: performance.now() });
            send(raw);
          };
          socket.addEventListener("message", event => {
            evidence.received.push({ frame: JSON.parse(String(event.data)) as Frame, clock: performance.now() });
          });
          return socket;
        } });
        window.AudioContext = new Proxy(window.AudioContext, { construct(target, args) {
          const audio = Reflect.construct(target, args) as AudioContext;
          const create = audio.createBufferSource.bind(audio);
          audio.createBufferSource = () => {
            const source = create();
            const start = source.start.bind(source), stop = source.stop.bind(source);
            source.start = when => { evidence.sources.push({ action: "start", clock: performance.now(), when, duration: source.buffer?.duration }); start(when); };
            source.stop = when => { evidence.sources.push({ action: "stop", clock: performance.now(), when }); stop(when); };
            return source;
          };
          return audio;
        } });
        class Recognition { continuous = true; interimResults = true; lang = "zh-CN"; start() {} stop() {} abort() {} }
        Object.assign(window, { SpeechRecognition: Recognition, webkitSpeechRecognition: Recognition });
      }, { port, kind, scenario });
      try {
        await page.goto("/conversation?role_id=e2e-unassigned");
        await page.getByRole("button", { name: "主页开始对话" }).click({ timeout: 5000 });
        await expect(page.getByRole("button", { name: "关闭麦克风" })).toBeVisible();
        expect((await request.get(`http://127.0.0.1:${port}/start`, { timeout: 2000 })).ok()).toBe(true);
        await expect.poll(() => page.evaluate(() => window.__productionHandoff.sent.some(({ frame }) =>
          frame.type === "playback_progress_v2" && frame.speech_id === "response:reply"
          && Number(frame.played_position_samples) > 1600)), { intervals: [20], timeout: 5000 }).toBe(true);
        expect((await request.get(`http://127.0.0.1:${port}/trigger`, { timeout: 2000 })).ok()).toBe(true);
        await expect.poll(async () => (await (await request.get(`http://127.0.0.1:${port}/evidence`, { timeout: 2000 })).json()).conditional,
          { intervals: [20], timeout: 1000 }).toBe(true);
        const prepared = await (await request.get(`http://127.0.0.1:${port}/evidence`, { timeout: 2000 })).json();
        expect(prepared).toMatchObject({ provider_calls: 2, conditional: true, commits: 0, delivered: "" });
        expect(await page.evaluate(() => window.__productionHandoff.received.some(({ frame }) =>
          frame.generation === 2 && ["assistant_text", "assistant_speech_text", "assistant_audio_chunk"].includes(String(frame.type))))).toBe(false);
        if (scenario === "revoked_pending") {
          expect((await request.get(`http://127.0.0.1:${port}/revise`, { timeout: 2000 })).ok()).toBe(true);
          await expect.poll(() => page.evaluate(() => window.__productionHandoff.received.some(({ frame }) =>
            frame.type === "assistant_text" && frame.text === "刚才没有及时响应，请再说一次。")),
            { timeout: 3000 }).toBe(true);
          const backend = await (await request.get(`http://127.0.0.1:${port}/evidence`, { timeout: 2000 })).json();
          expect(backend).toMatchObject({ provider_calls: 2, commits: 1, candidate_cancelled: false,
            candidate_exited: false, pending_owned: true, retained_input: true });
          const evidence = await page.evaluate(() => window.__productionHandoff);
          expect(evidence.received.some(({ frame }) => frame.type === "assistant_audio_chunk" && Number(frame.generation) > 1)).toBe(false);
          expect(evidence.received.some(({ frame }) => ["assistant_text", "assistant_speech_text"].includes(String(frame.type))
            && frame.text === "补充后的回答。")).toBe(false);
          expect((await request.get(`http://127.0.0.1:${port}/release`, { timeout: 2000 })).ok()).toBe(true);
          await expect.poll(async () => (await (await request.get(`http://127.0.0.1:${port}/evidence`, { timeout: 2000 })).json()).candidate_exited).toBe(true);
          return;
        }
        await expect.poll(() => page.evaluate(() => window.__productionHandoff.sent.filter(({ frame }) =>
          frame.type === "output_stop_result" && frame.outcome === "queue_stopped").length), { timeout: 3000 }).toBe(1);
        await expect.poll(() => page.evaluate(() => window.__productionHandoff.sent.some(({ frame }) =>
          frame.type === "playback_progress_v2" && frame.generation === 2)), { timeout: 3000 }).toBe(true);
        const evidence = await page.evaluate(() => window.__productionHandoff);
        const result = evidence.sent.find(({ frame }) => frame.type === "output_stop_result")!;
        expect(result.frame).toMatchObject({ output_epoch: "epoch", speech_id: "response:reply",
          generation: 1, outcome: "queue_stopped", played_position_samples: 16000 });
        const command = evidence.received.find(({ frame }) => frame.type === "assistant_speech_cancelled"
          && frame.sentence_permit)!;
        expect(command.frame.sentence_permit).toMatchObject({ audio_end_samples: 16000, sample_rate_hz: 16000 });
        const newFrames = evidence.received.filter(({ frame }) => frame.generation === 2
          && ["assistant_text", "assistant_speech_text", "assistant_audio_chunk"].includes(String(frame.type)));
        expect(newFrames.length).toBeGreaterThan(0);
        expect(newFrames.every(({ clock }) => clock >= result.clock)).toBe(true);
        // The real output schedules one-sample empty terminal markers too.
        // Count actual PCM sources separately and still verify all replacement
        // scheduling occurs after the physical stop receipt.
        const starts = evidence.sources.filter(source => source.action === "start");
        expect(starts).toHaveLength(4);
        const audio = starts.filter(source => Number(source.duration) > 1 / 16000);
        expect(audio).toHaveLength(2);
        expect(starts.slice(2).every(source => source.clock >= result.clock)).toBe(true);
        expect(Number(audio[1].when)).toBeGreaterThanOrEqual(Number(audio[0].when) + 1);
        expect(evidence.sources.some(source => source.action === "stop" && source.when !== undefined
          && Math.abs(source.when - (Number(audio[0].when) + 1)) < 1 / 16000)).toBe(true);
        const backend = await (await request.get(`http://127.0.0.1:${port}/evidence`, { timeout: 2000 })).json();
        expect(backend).toMatchObject({ provider_calls: 2, conditional: true, commits: 1, delivered: "第一句。" });
        expect(backend.prefetch).toContain("prepared");
      } finally {
        const releaseError = await request.get(`http://127.0.0.1:${port}/release`, { timeout: 2000 })
          .then(() => null, (error: Error) => error.message);
        const artifact = info.outputPath("production-sentence-handoff.json");
        await writeFile(artifact, JSON.stringify({
          browser: await page.evaluate(() => window.__productionHandoff).catch(() => null),
          backend: await request.get(`http://127.0.0.1:${port}/evidence`, { timeout: 2000 })
            .then(response => response.json()).catch((error: Error) => ({ evidence_error: error.message })),
          releaseError, fixtureErrors, pageErrors,
        }, null, 2));
        await info.attach("production-sentence-handoff", { path: artifact, contentType: "application/json" });
      }
    });
  }
}
