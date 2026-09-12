"use client";

import { useEffect, useRef, useState } from "react";
import type { ConversationState } from "@/hooks/use-voice-session";
import { useBottomVoiceStyle } from "@/hooks/use-bottom-voice-style";
import { bottomVoiceLevel } from "@/lib/bottom-voice-style";
import { paintBottomVoice } from "./bottom-voice-renderer";
import styles from "./bottom-voice.module.css";

interface BottomVoiceEdgeProps {
  state: ConversationState;
  level: number;
  muted: boolean;
  connected: boolean;
  reducedMotion: boolean;
}

export function BottomVoiceEdge({ state, level, muted, connected, reducedMotion }: BottomVoiceEdgeProps) {
  const { style } = useBottomVoiceStyle();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const latest = useRef({ state, level, muted, connected, reducedMotion, style });
  const wake = useRef<(() => void) | null>(null);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    latest.current = { state, level, muted, connected, reducedMotion, style };
    wake.current?.();
  }, [state, level, muted, connected, reducedMotion, style]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) { setFallback(true); return; }
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    let stopped = false;
    let last = 0;
    let time = 0;
    let displayedLevel = 0;
    let width = 0;
    let height = 0;
    let pixelRatio = 1;

    function resize() {
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * pixelRatio);
      canvas.height = Math.round(height * pixelRatio);
      requestFrame();
    }

    function requestFrame() {
      if (!frame && !stopped && !document.hidden) frame = requestAnimationFrame(draw);
    }

    function draw(now: number) {
      frame = 0;
      if (stopped || !context) return;
      const current = latest.current;
      const quietMotion = current.reducedMotion || motion.matches;
      const target = bottomVoiceLevel(current.state, current.level, current.muted, current.connected);
      const delta = Math.min((now - (last || now)) / 1000, .05);
      last = now;
      displayedLevel = quietMotion ? target : displayedLevel + (target - displayedLevel)
        * (1 - Math.exp(-delta / (target > displayedLevel ? .075 : .23)));
      const displayState = !current.connected ? "error"
        : current.muted && current.state !== "speaking" ? "muted" : current.state;
      if (!quietMotion) time += delta * (target > 0 ? .82 : .3);
      if (width && height) {
        context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
        paintBottomVoice(context, width, height, current.style, displayState, displayedLevel, quietMotion ? .3 : time);
      }
      if (!quietMotion && (target > 0 || displayedLevel > .001 || displayState === "thinking")) requestFrame();
    }

    function onVisibility() {
      if (document.hidden && frame) { cancelAnimationFrame(frame); frame = 0; }
      last = 0;
      requestFrame();
    }
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    motion.addEventListener("change", requestFrame);
    document.addEventListener("visibilitychange", onVisibility);
    wake.current = requestFrame;
    resize();
    return () => {
      stopped = true;
      wake.current = null;
      cancelAnimationFrame(frame);
      observer.disconnect();
      motion.removeEventListener("change", requestFrame);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <div className={styles.edge} data-bottom-voice-style={style} aria-hidden="true">
      <canvas ref={canvasRef} />
      {fallback && <span className={styles.fallback} />}
    </div>
  );
}
