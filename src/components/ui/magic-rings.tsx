"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";
import styles from "./magic-rings.module.css";

const vertexShader = `
void main() {
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const fragmentShader = `
precision highp float;
uniform float uTime, uAttenuation, uLineThickness;
uniform float uBaseRadius, uRadiusStep, uScaleRate;
uniform float uOpacity, uNoiseAmount, uRotation, uRingGap;
uniform float uFadeIn, uFadeOut, uHoverAmount, uHoverScale, uBurst;
uniform float uCoverageAlpha;
uniform vec2 uResolution;
uniform vec3 uColor, uColorTwo;
uniform int uRingCount;
const float HP = 1.5707963;
const float CYCLE = 3.45;

float fade(float t) {
  return t < uFadeIn ? smoothstep(0.0, uFadeIn, t) : 1.0 - smoothstep(uFadeOut, CYCLE - 0.2, t);
}

float ring(vec2 p, float ri, float cut, float t0, float px) {
  float t = mod(uTime + t0, CYCLE);
  float r = ri + t / CYCLE * uScaleRate;
  float d = abs(length(p) - r);
  float a = atan(abs(p.y), abs(p.x)) / HP;
  float th = max(1.0 - a, 0.5) * px * uLineThickness;
  float h = (1.0 - smoothstep(th, th * 1.5, d)) + 1.0;
  d += pow(cut * a, 3.0) * r;
  return h * exp(-uAttenuation * d) * fade(t);
}

void main() {
  float px = 1.0 / min(uResolution.x, uResolution.y);
  vec2 p = (gl_FragCoord.xy - 0.5 * uResolution.xy) * px;
  float cr = cos(uRotation), sr = sin(uRotation);
  p = mat2(cr, -sr, sr, cr) * p;
  float sc = mix(1.0, uHoverScale, uHoverAmount) + uBurst * 0.3;
  p /= sc;
  vec3 c = vec3(0.0);
  float coverage = 0.0;
  float rcf = max(float(uRingCount) - 1.0, 1.0);
  for (int i = 0; i < 10; i++) {
    if (i >= uRingCount) break;
    float fi = float(i);
    vec3 rc = mix(uColor, uColorTwo, fi / rcf);
    float ringAmount = ring(p, uBaseRadius + fi * uRadiusStep, pow(uRingGap, fi), i == 0 ? 0.0 : 2.95 * fi, px);
    c = mix(c, rc, vec3(ringAmount));
    coverage = max(coverage, ringAmount);
  }
  c *= 1.0 + uBurst * 2.0;
  float n = fract(sin(dot(gl_FragCoord.xy + uTime * 100.0, vec2(12.9898, 78.233))) * 43758.5453);
  c += (n - 0.5) * uNoiseAmount;
  float intensity = max(c.r, max(c.g, c.b));
  vec3 emissiveColor = intensity > 0.0001 ? clamp(c / intensity, 0.0, 1.0) : vec3(0.0);
  vec3 outputColor = mix(emissiveColor, clamp(c, 0.0, 1.0), uCoverageAlpha);
  float outputAlpha = mix(intensity, coverage, uCoverageAlpha);
  gl_FragColor = vec4(outputColor, clamp(outputAlpha * uOpacity, 0.0, 1.0));
}
`;

export type MagicRingsProps = {
  color?: string;
  colorTwo?: string;
  ringCount?: number;
  speed?: number;
  attenuation?: number;
  lineThickness?: number;
  baseRadius?: number;
  radiusStep?: number;
  scaleRate?: number;
  opacity?: number;
  noiseAmount?: number;
  rotation?: number;
  ringGap?: number;
  fadeIn?: number;
  fadeOut?: number;
  hoverScale?: number;
  clickBurst?: boolean;
  alphaMode?: "luminance" | "coverage";
};

export function createMagicRingsContext(canvas: HTMLCanvasElement): WebGL2RenderingContext | null {
  try {
    return canvas.getContext("webgl2", { alpha: true, antialias: false });
  } catch {
    return null;
  }
}

export default function MagicRings({
  color = "#6de7ff",
  colorTwo = "#a18dff",
  speed = 0.65,
  ringCount = 5,
  attenuation = 13,
  lineThickness = 1.6,
  baseRadius = 0.19,
  radiusStep = 0.075,
  scaleRate = 0.08,
  opacity = 0.9,
  noiseAmount = 0.025,
  rotation = -12,
  ringGap = 1.35,
  fadeIn = 0.7,
  fadeOut = 0.5,
  hoverScale = 1.08,
  clickBurst = true,
  alphaMode = "luminance",
}: MagicRingsProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const propsRef = useRef({ color, colorTwo, speed, ringCount, attenuation, lineThickness, baseRadius, radiusStep, scaleRate, opacity, noiseAmount, rotation, ringGap, fadeIn, fadeOut, hoverScale, clickBurst, alphaMode });
  propsRef.current = { color, colorTwo, speed, ringCount, attenuation, lineThickness, baseRadius, radiusStep, scaleRate, opacity, noiseAmount, rotation, ringGap, fadeIn, fadeOut, hoverScale, clickBurst, alphaMode };

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const canvas = document.createElement("canvas");
    const context = createMagicRingsContext(canvas);
    if (!context) {
      mount.dataset.unavailable = "true";
      return;
    }

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ canvas, context, alpha: true, antialias: false });
    } catch {
      mount.dataset.unavailable = "true";
      return;
    }
    if (!renderer.capabilities.isWebGL2) {
      renderer.dispose();
      mount.dataset.unavailable = "true";
      return;
    }

    renderer.setClearColor(0x000000, 0);
    renderer.domElement.setAttribute("aria-hidden", "true");
    mount.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-0.5, 0.5, 0.5, -0.5, 0.1, 10);
    camera.position.z = 1;
    const uniforms = {
      uTime: { value: 0 }, uAttenuation: { value: 0 }, uResolution: { value: new THREE.Vector2() },
      uColor: { value: new THREE.Color() }, uColorTwo: { value: new THREE.Color() },
      uLineThickness: { value: 0 }, uBaseRadius: { value: 0 }, uRadiusStep: { value: 0 },
      uScaleRate: { value: 0 }, uRingCount: { value: 0 }, uOpacity: { value: 1 },
      uNoiseAmount: { value: 0 }, uRotation: { value: 0 }, uRingGap: { value: 1.35 },
      uFadeIn: { value: 0.7 }, uFadeOut: { value: 0.5 }, uHoverAmount: { value: 0 },
      uHoverScale: { value: 1 }, uBurst: { value: 0 }, uCoverageAlpha: { value: 0 },
    };
    const material = new THREE.ShaderMaterial({ vertexShader, fragmentShader, uniforms, transparent: true, depthTest: false });
    const geometry = new THREE.PlaneGeometry(1, 1);
    scene.add(new THREE.Mesh(geometry, material));
    let frameId = 0;
    let visible = false;
    let pageVisible = !document.hidden;
    let hovered = false;
    let hoverAmount = 0;
    let burst = 0;
    let elapsed = 0;
    let lastTime = 0;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const resize = () => {
      const width = mount.clientWidth;
      const height = mount.clientHeight;
      const dpr = Math.min(window.devicePixelRatio, 2);
      renderer.setPixelRatio(dpr);
      renderer.setSize(width, height, false);
      uniforms.uResolution.value.set(width * dpr, height * dpr);
    };
    const render = (time: number) => {
      frameId = requestAnimationFrame(render);
      const props = propsRef.current;
      const delta = lastTime === 0 ? 0 : Math.min(time - lastTime, 100);
      lastTime = time;
      if (!reducedMotion) elapsed += delta * 0.001 * props.speed;
      hoverAmount += ((hovered ? 1 : 0) - hoverAmount) * 0.08;
      burst *= 0.94;
      if (burst < 0.001) burst = 0;
      uniforms.uTime.value = elapsed;
      uniforms.uAttenuation.value = props.attenuation;
      uniforms.uColor.value.set(props.color);
      uniforms.uColorTwo.value.set(props.colorTwo);
      uniforms.uLineThickness.value = props.lineThickness;
      uniforms.uBaseRadius.value = props.baseRadius;
      uniforms.uRadiusStep.value = props.radiusStep;
      uniforms.uScaleRate.value = props.scaleRate;
      uniforms.uRingCount.value = Math.min(Math.max(props.ringCount, 1), 10);
      uniforms.uOpacity.value = props.opacity;
      uniforms.uNoiseAmount.value = props.noiseAmount;
      uniforms.uRotation.value = THREE.MathUtils.degToRad(props.rotation);
      uniforms.uRingGap.value = props.ringGap;
      uniforms.uFadeIn.value = props.fadeIn;
      uniforms.uFadeOut.value = props.fadeOut;
      uniforms.uHoverAmount.value = hoverAmount;
      uniforms.uHoverScale.value = props.hoverScale;
      uniforms.uBurst.value = props.clickBurst ? burst : 0;
      uniforms.uCoverageAlpha.value = props.alphaMode === "coverage" ? 1 : 0;
      renderer.render(scene, camera);
      if (reducedMotion) stop();
    };
    const start = () => {
      if (visible && pageVisible && frameId === 0) {
        lastTime = 0;
        frameId = requestAnimationFrame(render);
      }
    };
    const stop = () => {
      if (frameId !== 0) cancelAnimationFrame(frameId);
      frameId = 0;
    };
    const onEnter = () => { hovered = true; start(); };
    const onLeave = () => { hovered = false; start(); };
    const onClick = () => { burst = 1; start(); };
    const onVisibility = () => {
      pageVisible = !document.hidden;
      if (pageVisible) start();
      else stop();
    };
    const resizeObserver = new ResizeObserver(resize);
    const intersectionObserver = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) start();
      else stop();
    });
    resize();
    resizeObserver.observe(mount);
    intersectionObserver.observe(mount);
    mount.addEventListener("pointerenter", onEnter);
    mount.addEventListener("pointerleave", onLeave);
    mount.addEventListener("click", onClick);
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stop();
      resizeObserver.disconnect();
      intersectionObserver.disconnect();
      mount.removeEventListener("pointerenter", onEnter);
      mount.removeEventListener("pointerleave", onLeave);
      mount.removeEventListener("click", onClick);
      document.removeEventListener("visibilitychange", onVisibility);
      renderer.domElement.remove();
      geometry.dispose();
      material.dispose();
      renderer.dispose();
    };
  }, []);

  return <div ref={mountRef} className={styles.rings} aria-hidden="true">
    <span className={styles.fallback}><i /><i /><i /></span>
  </div>;
}
