/// <reference types="@webgpu/types" />

import type { LiquidGlassOrbParams } from "./liquid-glass-orb-params";

const ORB_UNIFORM_FLOAT_COUNT = 128;
const ORB_COLOR_OFFSET = 32;
const PALETTE_STOPS = [
  "#F7FBFF", "#EFF6FD", "#E0EEF9", "#D4E6F7", "#BBD5F3", "#A6C7F0",
  "#87B0EB", "#6F9EE8", "#6F9EE8", "#6F9EE8", "#6F9EE8", "#6F9EE8",
] as const;

const ENTRY_POINTS = `
struct VOut {
  @builtin(position) pos: vec4<f32>,
  @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) i: u32) -> VOut {
  var p = array<vec2<f32>, 3>(
    vec2<f32>(-1.0, -1.0),
    vec2<f32>( 3.0, -1.0),
    vec2<f32>(-1.0,  3.0),
  );
  var out: VOut;
  out.pos = vec4<f32>(p[i], 0.0, 1.0);
  let uv01 = (p[i] + vec2<f32>(1.0)) * 0.5;
  out.uv = vec2<f32>(uv01.x, 1.0 - uv01.y);
  return out;
}

@fragment
fn fs_main(in: VOut) -> @location(0) vec4<f32> {
  let c = orbGlassLiquidAnim(in.uv);
  let fc = vec2<f32>(in.uv.x, 1.0 - in.uv.y) * u.size;
  let uv = (2.0 * fc - u.size) / max(min(u.size.x, u.size.y), 1.0);
  let rad = max(u.radius, 0.05);
  let t = u.time * u.speed;
  let contourRad = rad * glsContourScale(uv, t, u.contourDeform);
  let q = (2.0 * fc - u.size) / u.size;
  let fitEnd = 1.0;
  let fitFeather = 2.0 / max(min(u.size.x, u.size.y), 1.0);
  let fitStart = min(mix(contourRad, fitEnd, 0.5), fitEnd - fitFeather);
  let fit = 1.0 - smoothstep(fitStart, fitEnd, max(abs(q.x), abs(q.y)));
  return vec4<f32>(c.rgb * fit, c.a * fit);
}
`;

let shaderSourcePromise: Promise<string> | null = null;

function loadShaderSource(): Promise<string> {
  shaderSourcePromise ??= fetch("/orbs/lersent001/effect.wgsl")
    .then((response) => {
      if (!response.ok) throw new Error(`Orb shader request failed (${response.status})`);
      return response.text();
    })
    .then((source) => `${source}\n${ENTRY_POINTS}`)
    .catch((error: unknown) => {
      shaderSourcePromise = null;
      throw error;
    });
  return shaderSourcePromise;
}

function rgba(hex: string): [number, number, number, number] {
  const value = hex.slice(1);
  return [
    Number.parseInt(value.slice(0, 2), 16) / 255,
    Number.parseInt(value.slice(2, 4), 16) / 255,
    Number.parseInt(value.slice(4, 6), 16) / 255,
    1,
  ];
}

function writeUniforms(
  target: Float32Array,
  width: number,
  height: number,
  time: number,
  params: LiquidGlassOrbParams,
) {
  target.fill(0);
  target[0] = width;
  target[1] = height;
  target[2] = time;
  target.set([
    params.speed, params.radius, params.zoom, params.warp, params.ridgeAmt,
    params.sharp, params.shade, params.sheen, params.gloss, params.shellMidAlpha,
    params.shellEdgeAlpha, params.exposure, 9, params.edgeSoftness, params.edgeGlow,
    0, params.glassEnabled ? 1 : 0, params.glassOpacity, params.contourDeform,
    params.bandDensity, params.chromaticShift, params.metalScale, params.metalStretch,
    params.metalAngle, params.metalOffset, params.metalPhase, params.metalEvolution,
    params.metalRoughness, params.metalDepth,
  ], 3);

  const colors = [
    params.colorA, params.colorB, params.colorC, params.colorD, params.highlightColor,
    params.shellInner, params.shellMid, params.shellEdge, params.sheenColor, params.specColor,
    params.canvasColor, params.glowColor, ...PALETTE_STOPS,
  ];
  colors.forEach((color, index) => target.set(rgba(color), ORB_COLOR_OFFSET + index * 4));
}

interface LiquidGlassRendererOptions {
  canvas: HTMLCanvasElement;
  getParams: () => LiquidGlassOrbParams;
  onError: (error: Error) => void;
  onReady: () => void;
}

export function createLiquidGlassOrbRenderer({
  canvas,
  getParams,
  onError,
  onReady,
}: LiquidGlassRendererOptions): () => void {
  let disposed = false;
  let failed = false;
  let animationFrame = 0;
  let device: GPUDevice | null = null;

  const fail = (error: Error) => {
    if (disposed || failed) return;
    failed = true;
    cancelAnimationFrame(animationFrame);
    device?.destroy();
    onError(error);
  };

  async function start() {
    try {
      if (!navigator.gpu) throw new Error("WebGPU is unavailable");
      const [source, adapter] = await Promise.all([
        loadShaderSource(),
        navigator.gpu.requestAdapter(),
      ]);
      if (!adapter) throw new Error("No WebGPU adapter is available");
      device = await adapter.requestDevice();
      if (disposed) {
        device.destroy();
        return;
      }

      const context = canvas.getContext("webgpu");
      if (!context) throw new Error("Unable to create a WebGPU canvas context");
      const format = navigator.gpu.getPreferredCanvasFormat();
      context.configure({ device, format, alphaMode: "premultiplied" });
      const shader = device.createShaderModule({ label: "lersent-liquid-glass-orb", code: source });
      const compilation = await shader.getCompilationInfo();
      const errors = compilation.messages.filter((message) => message.type === "error");
      if (errors.length > 0) throw new Error(errors.map((error) => error.message).join("\n"));

      const pipeline = device.createRenderPipeline({
        label: "lersent-liquid-glass-orb-pipeline",
        layout: "auto",
        vertex: { module: shader, entryPoint: "vs_main" },
        fragment: { module: shader, entryPoint: "fs_main", targets: [{ format }] },
        primitive: { topology: "triangle-list" },
      });
      const values = new Float32Array(ORB_UNIFORM_FLOAT_COUNT);
      const uniformBuffer = device.createBuffer({
        size: values.byteLength,
        usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
      });
      const bindGroup = device.createBindGroup({
        layout: pipeline.getBindGroupLayout(0),
        entries: [{ binding: 0, resource: { buffer: uniformBuffer } }],
      });
      const startedAt = performance.now();
      let ready = false;

      device.lost.then((info) => {
        fail(new Error(`WebGPU device lost: ${info.message || info.reason}`));
      });
      device.addEventListener("uncapturederror", (event) => {
        event.preventDefault();
        fail(new Error(`WebGPU rendering error: ${event.error.message}`));
      });

      const frame = (now: number) => {
        if (disposed || failed || !device) return;
        try {
          const dpr = Math.min(window.devicePixelRatio || 1, 2);
          const width = Math.max(1, Math.floor(canvas.clientWidth * dpr));
          const height = Math.max(1, Math.floor(canvas.clientHeight * dpr));
          if (canvas.width !== width || canvas.height !== height) {
            canvas.width = width;
            canvas.height = height;
          }
          writeUniforms(values, width, height, (now - startedAt) / 1000, getParams());
          device.queue.writeBuffer(uniformBuffer, 0, values);
          const encoder = device.createCommandEncoder();
          const pass = encoder.beginRenderPass({
            colorAttachments: [{
              view: context.getCurrentTexture().createView(),
              clearValue: { r: 0, g: 0, b: 0, a: 0 },
              loadOp: "clear",
              storeOp: "store",
            }],
          });
          pass.setPipeline(pipeline);
          pass.setBindGroup(0, bindGroup);
          pass.draw(3);
          pass.end();
          device.queue.submit([encoder.finish()]);
          if (!ready) {
            ready = true;
            onReady();
          }
          animationFrame = requestAnimationFrame(frame);
        } catch (error) {
          fail(error instanceof Error ? error : new Error(String(error)));
        }
      };
      animationFrame = requestAnimationFrame(frame);
    } catch (error) {
      fail(error instanceof Error ? error : new Error(String(error)));
    }
  }

  void start();
  return () => {
    disposed = true;
    cancelAnimationFrame(animationFrame);
    device?.destroy();
  };
}
