"use client";
import { LocalizedText } from "@/components/language/language-provider";

import { animate, motion, useMotionValue, useReducedMotion, useTransform } from "motion/react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type MouseEvent, type PointerEvent, type ReactNode } from "react";
import styles from "./rubber-segment.module.css";

const EASE_OUT: [number, number, number, number] = [0.23, 1, 0.32, 1];
const SPRING_UI = { type: "spring" as const, duration: 0.3, bounce: 0 };
const SPRING_MOMENTUM = { type: "spring" as const, duration: 0.4, bounce: 0.2 };
const SPRING_RELAX = { type: "spring" as const, duration: 0.16, bounce: 0 };
const DILATE = 0.19;
const HANDOFF = 0.15;
const FLICK = 110;
const MAX_VELOCITY = 2000;
const DEADZONE = 4;
const SLOP = 10;
const RUBBER = 0.55;
const SIZES = {
  sm: { height: 28, font: 12, pad: 10, min: 36 },
  md: { height: 36, font: 13, pad: 14, min: 44 },
  lg: { height: 44, font: 14, pad: 18, min: 48 },
};

export type RubberSegmentItem = string | {
  value: string;
  label: ReactNode;
  icon?: ReactNode;
  onPointerEnter?: () => void;
  onPointerDown?: () => void;
  onFocus?: () => void;
  onClick?: () => void;
};

type RubberSegmentProps = {
  items: RubberSegmentItem[];
  value?: string;
  defaultValue?: string;
  onChange?: (value: string, index: number) => void;
  trackColor?: string;
  thumbColor?: string;
  textColor?: string;
  activeTextColor?: string;
  size?: keyof typeof SIZES;
  radius?: number;
  inset?: number;
  equalSlots?: boolean;
  stretch?: number;
  squash?: number;
  speed?: number;
  glide?: number;
  draggable?: boolean;
  disabled?: boolean;
  className?: string;
  "aria-label"?: string;
  "data-transparency"?: number | string;
  "data-glass-blur"?: number | string;
};

type Slot = { l: number; r: number };
type DragState = {
  id: number;
  x0: number;
  slot: number;
  onThumb: boolean;
  live: boolean;
  offset: number;
  width: number;
  history: Array<[number, number]>;
};

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
const rubber = (over: number, dimension: number) => (over * dimension * RUBBER) / (dimension + RUBBER * Math.abs(over));
const project = (velocity: number, glide: number) => {
  const decay = 1 - 0.1 * Math.pow(0.05, glide / 100);
  return ((velocity / 1000) * decay) / (1 - decay);
};
const velocityOf = (history: Array<[number, number]>, now: number) => {
  const recent = history.filter(([time]) => now - time <= 100);
  if (recent.length < 2) return 0;
  const [firstTime, firstX] = recent[0];
  const [lastTime, lastX] = recent[recent.length - 1];
  return lastTime - firstTime >= 8 ? ((lastX - firstX) / (lastTime - firstTime)) * 1000 : 0;
};
const nearestSlot = (slots: Slot[], x: number) => slots.reduce((best, slot, index) => (
  Math.abs((slot.l + slot.r) / 2 - x) < Math.abs((slots[best].l + slots[best].r) / 2 - x) ? index : best
), 0);

export default function RubberSegment({
  items,
  value,
  defaultValue,
  onChange,
  trackColor = "color-mix(in srgb, var(--surface-raised) calc(var(--panel-surface-alpha, .56) * 100%), transparent)",
  thumbColor = "var(--accent-surface)",
  textColor = "var(--text-dim)",
  activeTextColor = "var(--text)",
  size = "md",
  radius = 14,
  inset = 3,
  equalSlots = true,
  stretch = 76,
  squash = 3,
  speed = 1,
  glide = 65,
  draggable = true,
  disabled = false,
  className = "",
  "aria-label": ariaLabel = "分段切换",
  "data-transparency": dataTransparency,
  "data-glass-blur": dataGlassBlur,
}: RubberSegmentProps) {
  const list = useMemo(() => items.map(item => typeof item === "string" ? { value: item, label: item } : item), [items]);
  const [innerValue, setInnerValue] = useState(defaultValue ?? list[0]?.value);
  const current = value ?? innerValue;
  const index = Math.max(0, list.findIndex(item => item.value === current));
  const reduceMotion = useReducedMotion();
  const trackRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const slots = useRef<Slot[]>([]);
  const box = useRef<DOMRect | null>(null);
  const committed = useRef(index);
  const handoff = useRef<ReturnType<typeof setTimeout> | null>(null);
  const drag = useRef<DragState | null>(null);
  const generation = useRef(0);
  const edgeLeft = useMotionValue(0);
  const edgeRight = useMotionValue(0);
  const innerWidth = useMotionValue(0);
  const thumbRadius = Math.max(0, radius - inset);
  const clipPath = useTransform(() => `inset(0 ${Math.max(0, innerWidth.get() - edgeRight.get())}px 0 ${Math.max(0, edgeLeft.get())}px round ${thumbRadius}px)`);
  const duration = (seconds: number) => seconds / Math.max(speed, 0.01);

  const clearHandoff = () => {
    if (handoff.current) clearTimeout(handoff.current);
    handoff.current = null;
  };
  const jumpTo = (target: number) => {
    const slot = slots.current[target];
    if (!slot) return;
    clearHandoff();
    generation.current += 1;
    edgeLeft.jump(slot.l);
    edgeRight.jump(slot.r);
  };
  const measure = () => {
    const track = trackRef.current;
    if (!track) return;
    const rect = track.getBoundingClientRect();
    box.current = rect;
    slots.current = list.map((_, itemIndex) => {
      const element = itemRefs.current[itemIndex];
      if (!element) return { l: 0, r: 0 };
      const itemRect = element.getBoundingClientRect();
      return { l: itemRect.left - rect.left - inset, r: itemRect.right - rect.left - inset };
    });
    innerWidth.set(rect.width - inset * 2);
    jumpTo(committed.current);
  };

  const listKey = list.map(item => item.value).join("|");
  useLayoutEffect(() => {
    measure();
    const observer = new ResizeObserver(measure);
    if (trackRef.current) observer.observe(trackRef.current);
    document.fonts?.ready.then(measure);
    return () => observer.disconnect();
    // Measurements intentionally rerun when the option layout changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listKey, size, inset, equalSlots]);

  useEffect(() => {
    if (!drag.current && committed.current !== index) {
      committed.current = index;
      jumpTo(index);
    }
  });

  useEffect(() => () => {
    clearHandoff();
    edgeLeft.stop();
    edgeRight.stop();
  }, [edgeLeft, edgeRight]);

  const commit = (target: number) => {
    committed.current = target;
    if (target === index || !list[target]) return;
    if (value === undefined) setInnerValue(list[target].value);
    onChange?.(list[target].value, target);
  };

  const land = (target: number, velocity: number | null, flick: boolean, withSquash: boolean) => {
    const destination = slots.current[target];
    if (!destination) return;
    const currentGeneration = ++generation.current;
    const direction = Math.sign((destination.l + destination.r) / 2 - (edgeLeft.get() + edgeRight.get()) / 2) || 1;
    const [lead, leadTo, trail, trailTo] = direction > 0
      ? [edgeRight, destination.r, edgeLeft, destination.l]
      : [edgeLeft, destination.l, edgeRight, destination.r];
    const velocityFor = (motionValue: typeof edgeLeft) => clamp(velocity === null ? motionValue.getVelocity() : velocity, -MAX_VELOCITY, MAX_VELOCITY);
    animate(lead, leadTo, { ...(flick ? SPRING_MOMENTUM : SPRING_UI), duration: duration(flick ? 0.4 : 0.3), velocity: velocityFor(lead) });
    const trailVelocity = velocityFor(trail);
    if (!withSquash || squash <= 0) {
      animate(trail, trailTo, { ...SPRING_UI, duration: duration(0.3), velocity: trailVelocity });
      return;
    }
    animate(trail, trailTo + direction * squash, { ...SPRING_UI, duration: duration(0.3), velocity: trailVelocity }).then(() => {
      if (generation.current === currentGeneration) animate(trail, trailTo, { ...SPRING_RELAX, duration: duration(0.16) });
    });
  };

  const travel = (from: number, target: number) => {
    const origin = slots.current[from];
    const destination = slots.current[target];
    if (!origin || !destination) return;
    clearHandoff();
    generation.current += 1;
    if (reduceMotion) {
      edgeLeft.jump(destination.l);
      edgeRight.jump(destination.r);
      return;
    }
    const stretchAmount = stretch / 100;
    const tween = { duration: duration(DILATE), ease: EASE_OUT };
    animate(edgeLeft, destination.l + (Math.min(origin.l, destination.l) - destination.l) * stretchAmount, tween);
    animate(edgeRight, destination.r + (Math.max(origin.r, destination.r) - destination.r) * stretchAmount, tween);
    handoff.current = setTimeout(() => land(target, null, false, true), duration(HANDOFF) * 1000);
  };

  const localX = (event: PointerEvent) => event.clientX - (box.current?.left ?? 0) - inset;
  const handlePointerDown = (event: PointerEvent<HTMLButtonElement>, itemIndex: number) => {
    if (disabled || drag.current || event.button !== 0 || !trackRef.current) return;
    box.current = trackRef.current.getBoundingClientRect();
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch {}
    const x = localX(event);
    const onThumb = draggable && x >= edgeLeft.get() && x <= edgeRight.get();
    drag.current = { id: event.pointerId, x0: x, slot: itemIndex, onThumb, live: false, offset: 0, width: 0, history: [[event.timeStamp, x]] };
    if (onThumb) {
      clearHandoff();
      generation.current += 1;
      edgeLeft.stop();
      edgeRight.stop();
    } else if (!reduceMotion) event.currentTarget.dataset.pressed = "";
  };
  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (!state || event.pointerId !== state.id || !state.onThumb) return;
    const x = localX(event);
    state.history.push([event.timeStamp, x]);
    if (state.history.length > 8) state.history.shift();
    if (!state.live) {
      if (Math.abs(x - state.x0) < DEADZONE) return;
      state.live = true;
      state.offset = x - edgeLeft.get();
      state.width = edgeRight.get() - edgeLeft.get();
      if (trackRef.current) trackRef.current.dataset.held = "";
    }
    const width = innerWidth.get();
    const left = x - state.offset;
    const maxLeft = width - state.width;
    if (reduceMotion) {
      const constrained = clamp(left, 0, maxLeft);
      edgeLeft.set(constrained);
      edgeRight.set(constrained + state.width);
    } else if (left < 0) {
      edgeLeft.set(0);
      edgeRight.set(state.width - rubber(-left, state.width));
    } else if (left > maxLeft) {
      edgeRight.set(width);
      edgeLeft.set(maxLeft + rubber(left - maxLeft, state.width));
    } else {
      edgeLeft.set(left);
      edgeRight.set(left + state.width);
    }
  };
  const release = () => {
    const state = drag.current;
    drag.current = null;
    if (!state) return null;
    if (trackRef.current) delete trackRef.current.dataset.held;
    const element = itemRefs.current[state.slot];
    if (element) delete element.dataset.pressed;
    return state;
  };
  const handlePointerUp = (event: PointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (!state || event.pointerId !== state.id) return;
    release();
    const x = localX(event);
    if (!state.live) {
      if (Math.abs(x - state.x0) <= SLOP && state.slot !== committed.current) {
        const from = committed.current;
        commit(state.slot);
        travel(from, state.slot);
      }
      return;
    }
    const velocity = velocityOf(state.history, event.timeStamp);
    const flick = Math.abs(velocity) > FLICK;
    let target = nearestSlot(slots.current, (edgeLeft.get() + edgeRight.get()) / 2 + project(velocity, glide));
    if (flick && target === committed.current) target = clamp(target + Math.sign(velocity), 0, list.length - 1);
    commit(target);
    if (reduceMotion) jumpTo(target);
    else land(target, velocity, flick, flick);
  };
  const handlePointerCancel = (event: PointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (!state || event.pointerId !== state.id) return;
    release();
    if (!state.live) return;
    if (reduceMotion) jumpTo(committed.current);
    else land(committed.current, null, false, false);
  };
  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return;
    const last = list.length - 1;
    let target: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") target = Math.min(last, index + 1);
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") target = Math.max(0, index - 1);
    else if (event.key === "Home") target = 0;
    else if (event.key === "End") target = last;
    if (target === null) return;
    event.preventDefault();
    if (target === index) return;
    commit(target);
    jumpTo(target);
    itemRefs.current[target]?.focus();
  };
  const handleClick = (event: MouseEvent<HTMLButtonElement>, target: number) => {
    // Pointer input is committed on pointerup so the thumb can also be dragged.
    // A zero detail identifies keyboard-generated clicks from Space or Enter.
    if (event.detail !== 0 || disabled || target === committed.current) return;
    const from = committed.current;
    commit(target);
    travel(from, target);
  };

  const preset = SIZES[size];
  const variables = {
    "--rs-track": trackColor,
    "--rs-thumb": thumbColor,
    "--rs-ink": textColor,
    "--rs-ink-active": activeTextColor,
    "--rs-radius": `${radius}px`,
    "--rs-inset": `${inset}px`,
    "--rs-thumb-radius": `${thumbRadius}px`,
    "--rs-h": `${preset.height}px`,
    "--rs-font": `${preset.font}px`,
    "--rs-pad": `${preset.pad}px`,
    "--rs-min": `${preset.min}px`,
  } as CSSProperties;

  return <div
    ref={trackRef}
    role="radiogroup"
    aria-label={ariaLabel}
    aria-disabled={disabled || undefined}
    data-transparency={dataTransparency}
    data-glass-blur={dataGlassBlur}
    data-equal={equalSlots ? "" : undefined}
    data-draggable={draggable && !disabled ? "" : undefined}
    className={`${styles.segment} ${className}`}
    style={variables}
    onPointerMove={handlePointerMove}
    onPointerUp={handlePointerUp}
    onPointerCancel={handlePointerCancel}
    onLostPointerCapture={handlePointerCancel}
  >
    {list.map((item, itemIndex) => <button
      key={item.value}
      ref={element => { itemRefs.current[itemIndex] = element; }}
      type="button"
      role="radio"
      aria-checked={itemIndex === index}
      tabIndex={itemIndex === index ? 0 : -1}
      disabled={disabled}
      className={styles.item}
      onPointerEnter={item.onPointerEnter}
      onFocus={item.onFocus}
      onPointerDown={event => {
        item.onPointerDown?.();
        handlePointerDown(event, itemIndex);
      }}
      onKeyDown={handleKeyDown}
      onClick={event => {
        item.onClick?.();
        handleClick(event, itemIndex);
      }}
    >{item.icon}{<LocalizedText text={item.label} />}</button>)}
    <motion.div className={styles.thumb} aria-hidden="true" style={{ clipPath }}>
      {list.map(item => <span key={item.value} className={`${styles.item} ${styles.copy}`}>{item.icon}{<LocalizedText text={item.label} />}</span>)}
    </motion.div>
  </div>;
}
