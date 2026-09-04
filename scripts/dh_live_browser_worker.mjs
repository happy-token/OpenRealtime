#!/usr/bin/env node

import { readFile, writeFile } from "node:fs/promises";
import { parseArgs } from "node:util";
import { chromium } from "@playwright/test";

const { values } = parseArgs({
  options: {
    "renderer-url": { type: "string" },
    audio: { type: "string" },
    "control-audio": { type: "string" },
    "raw-video": { type: "string" },
    evidence: { type: "string" },
    "duration-ms": { type: "string" },
    "canvas-width": { type: "string", default: "720" },
    "canvas-height": { type: "string", default: "1080" },
  },
  strict: true,
});

for (const name of ["renderer-url", "audio", "control-audio", "raw-video", "evidence", "duration-ms"]) {
  if (!values[name]) throw new Error(`Missing required option: --${name}`);
}

const rendererUrl = new URL(values["renderer-url"]);
if (rendererUrl.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(rendererUrl.hostname)) {
  throw new Error("Renderer URL must use loopback HTTP");
}
const durationMs = Number(values["duration-ms"]);
if (!Number.isSafeInteger(durationMs) || durationMs <= 0 || durationMs > 60_000) {
  throw new Error("Duration must be an integer between 1 and 60000 milliseconds");
}
const canvasWidth = Number(values["canvas-width"]);
const canvasHeight = Number(values["canvas-height"]);
if (
  !Number.isSafeInteger(canvasWidth)
  || !Number.isSafeInteger(canvasHeight)
  || canvasWidth <= 0
  || canvasHeight <= 0
  || canvasWidth > 4096
  || canvasHeight > 4096
) {
  throw new Error("Canvas dimensions must be positive integers no larger than 4096");
}

const audioBytes = new Uint8Array(await readFile(values.audio));
const controlAudioBytes = new Uint8Array(await readFile(values["control-audio"]));
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: canvasWidth, height: canvasHeight } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto(rendererUrl.href, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(({ expectedWidth, expectedHeight }) => {
    const canvas = document.querySelector("#canvas_video");
    return getComputedStyle(document.querySelector("#loadingSpinner")).display === "none"
      && canvas?.width === expectedWidth
      && canvas?.height === expectedHeight
      && typeof Module?._setAudioBuffer === "function"
      && typeof Module?._updateBlendShape === "function";
  }, { expectedWidth: canvasWidth, expectedHeight: canvasHeight }, { timeout: 30_000 });

  const evidence = await page.evaluate(async ({ speechBytes, silenceBytes, benchmarkDurationMs }) => {
    const canvas = document.querySelector("#canvas_video");
    const webgl = document.querySelector("#canvas_gl").getContext("webgl2");
    if (!canvas.captureStream || !webgl || typeof MediaRecorder !== "function") {
      throw new Error("Canvas capture, MediaRecorder, and WebGL2 are required");
    }
    const mimeType = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"]
      .find((candidate) => MediaRecorder.isTypeSupported(candidate));
    if (!mimeType) throw new Error("No supported WebM MediaRecorder codec");

    const state = {
      phase: null,
      phaseStartMs: 0,
      controlTimestampsMs: [],
      controlBlendShapeDeltas: [],
      speechTimestampsMs: [],
      speechBlendShapeDeltas: [],
      previousBlendShape: null,
      setAudioBufferCalls: 0,
      speechAudioBytes: 0,
      controlAudioBytes: 0,
    };
    const originalUpdateBlendShape = Module._updateBlendShape.bind(Module);
    Module._updateBlendShape = (pointer, size) => {
      const result = originalUpdateBlendShape(pointer, size);
      if (!state.phase) return result;
      const now = performance.now();
      const current = Array.from(new Float32Array(Module.HEAPU8.buffer, pointer, 12));
      let delta = 0;
      if (state.previousBlendShape) {
        delta = Math.max(...current.map((value, index) => (
          Math.abs(value - state.previousBlendShape[index])
        )));
      }
      const timestamps = state.phase === "control"
        ? state.controlTimestampsMs : state.speechTimestampsMs;
      const deltas = state.phase === "control"
        ? state.controlBlendShapeDeltas : state.speechBlendShapeDeltas;
      timestamps.push(now - state.phaseStartMs);
      deltas.push(delta);
      state.previousBlendShape = current;
      return result;
    };

    const submitAndObserve = async (bytes, phase) => {
      const audio = Uint8Array.from(bytes);
      const pointer = Module._malloc(audio.byteLength);
      try {
        Module.HEAPU8.set(audio, pointer);
        state.phase = phase;
        state.phaseStartMs = performance.now();
        state.previousBlendShape = null;
        state.setAudioBufferCalls += 1;
        if (phase === "control") state.controlAudioBytes = audio.byteLength;
        else state.speechAudioBytes = audio.byteLength;
        Module._setAudioBuffer(pointer, audio.byteLength);
        await new Promise((resolve) => setTimeout(resolve, benchmarkDurationMs));
        state.phase = null;
      } finally {
        Module._free(pointer);
      }
    };

    await submitAndObserve(silenceBytes, "control");
    await new Promise((resolve) => setTimeout(resolve, 200));

    const chunks = [];
    const recorder = new MediaRecorder(canvas.captureStream(25), { mimeType });
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    });
    const stopped = new Promise((resolve) => recorder.addEventListener("stop", resolve, { once: true }));
    recorder.start(100);
    await new Promise((resolve) => requestAnimationFrame(resolve));

    await submitAndObserve(speechBytes, "speech");
    recorder.stop();
    await stopped;
    window.__dhLiveBenchmarkBlob = new Blob(chunks, { type: mimeType });

    return {
      canvas_width: canvas.width,
      canvas_height: canvas.height,
      speech_audio_bytes: state.speechAudioBytes,
      control_audio_bytes: state.controlAudioBytes,
      set_audio_buffer_calls: state.setAudioBufferCalls,
      control_timestamps_ms: state.controlTimestampsMs,
      control_blend_shape_deltas: state.controlBlendShapeDeltas,
      speech_timestamps_ms: state.speechTimestampsMs,
      speech_blend_shape_deltas: state.speechBlendShapeDeltas,
      browser_version: navigator.userAgent,
      webgl_version: webgl.getParameter(webgl.VERSION),
    };
  }, {
    speechBytes: Array.from(audioBytes),
    silenceBytes: Array.from(controlAudioBytes),
    benchmarkDurationMs: durationMs,
  });

  if (pageErrors.length) throw new Error(`Renderer page errors: ${pageErrors.join("; ")}`);
  const downloadPromise = page.waitForEvent("download");
  await page.evaluate(() => {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(window.__dhLiveBenchmarkBlob);
    link.download = "dh-live-benchmark.webm";
    link.click();
  });
  const download = await downloadPromise;
  await download.saveAs(values["raw-video"]);
  await writeFile(values.evidence, `${JSON.stringify(evidence, null, 2)}\n`, { flag: "wx" });
} finally {
  await browser.close();
}
