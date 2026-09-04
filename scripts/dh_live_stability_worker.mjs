#!/usr/bin/env node

import { readFile, writeFile } from "node:fs/promises";
import { parseArgs } from "node:util";
import { chromium } from "@playwright/test";

const { values } = parseArgs({
  options: {
    "renderer-url": { type: "string" },
    audio: { type: "string" },
    evidence: { type: "string" },
    "duration-ms": { type: "string" },
    "clip-duration-ms": { type: "string" },
    "canvas-width": { type: "string", default: "720" },
    "canvas-height": { type: "string", default: "1280" },
  },
  strict: true,
});

for (const name of [
  "renderer-url",
  "audio",
  "evidence",
  "duration-ms",
  "clip-duration-ms",
]) {
  if (!values[name]) throw new Error(`Missing required option: --${name}`);
}

const rendererUrl = new URL(values["renderer-url"]);
if (rendererUrl.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(rendererUrl.hostname)) {
  throw new Error("Renderer URL must use loopback HTTP");
}
const durationMs = Number(values["duration-ms"]);
const clipDurationMs = Number(values["clip-duration-ms"]);
const canvasWidth = Number(values["canvas-width"]);
const canvasHeight = Number(values["canvas-height"]);
if (!Number.isSafeInteger(durationMs) || durationMs < 1_000 || durationMs > 660_000) {
  throw new Error("Duration must be an integer between 1000 and 660000 milliseconds");
}
if (!Number.isSafeInteger(clipDurationMs) || clipDurationMs < 100 || clipDurationMs > 60_000) {
  throw new Error("Clip duration must be an integer between 100 and 60000 milliseconds");
}
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

  const evidence = await page.evaluate(async ({ bytes, benchmarkDurationMs, sourceClipMs }) => {
    const canvas = document.querySelector("#canvas_video");
    const webgl = document.querySelector("#canvas_gl").getContext("webgl2");
    if (!webgl) throw new Error("WebGL2 is required");
    const state = {
      startMs: 0,
      timestampsMs: [],
      blendShapeDeltas: [],
      audioSubmissionTimestampsMs: [],
      previousBlendShape: null,
      setAudioBufferCalls: 0,
    };
    const originalUpdateBlendShape = Module._updateBlendShape.bind(Module);
    Module._updateBlendShape = (pointer, size) => {
      const result = originalUpdateBlendShape(pointer, size);
      if (!state.startMs) return result;
      const current = Array.from(new Float32Array(Module.HEAPU8.buffer, pointer, 12));
      let delta = 0;
      if (state.previousBlendShape) {
        delta = Math.max(...current.map((value, index) => (
          Math.abs(value - state.previousBlendShape[index])
        )));
      }
      state.timestampsMs.push(performance.now() - state.startMs);
      state.blendShapeDeltas.push(delta);
      state.previousBlendShape = current;
      return result;
    };

    const audio = Uint8Array.from(bytes);
    const pointer = Module._malloc(audio.byteLength);
    try {
      Module.HEAPU8.set(audio, pointer);
      state.startMs = performance.now();
      const targetEndMs = state.startMs + benchmarkDurationMs;
      while (performance.now() < targetEndMs) {
        state.previousBlendShape = null;
        state.setAudioBufferCalls += 1;
        state.audioSubmissionTimestampsMs.push(performance.now() - state.startMs);
        Module._setAudioBuffer(pointer, audio.byteLength);
        const observeMs = Math.min(sourceClipMs, targetEndMs - performance.now());
        await new Promise((resolve) => setTimeout(resolve, observeMs));
      }
    } finally {
      state.startMs = 0;
      Module._free(pointer);
    }

    return {
      canvas_width: canvas.width,
      canvas_height: canvas.height,
      audio_bytes: audio.byteLength,
      requested_duration_ms: benchmarkDurationMs,
      clip_duration_ms: sourceClipMs,
      set_audio_buffer_calls: state.setAudioBufferCalls,
      audio_submission_timestamps_ms: state.audioSubmissionTimestampsMs,
      timestamps_ms: state.timestampsMs,
      blend_shape_deltas: state.blendShapeDeltas,
      browser_version: navigator.userAgent,
      webgl_version: webgl.getParameter(webgl.VERSION),
    };
  }, {
    bytes: Array.from(audioBytes),
    benchmarkDurationMs: durationMs,
    sourceClipMs: clipDurationMs,
  });

  if (pageErrors.length) throw new Error(`Renderer page errors: ${pageErrors.join("; ")}`);
  await writeFile(values.evidence, `${JSON.stringify(evidence)}\n`, { flag: "wx" });
} finally {
  await browser.close();
}
