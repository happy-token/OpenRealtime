"use client";

import "@ncdai/react-wheel-picker/style.css";
import {
  WheelPicker as PrimitiveWheelPicker,
  WheelPickerWrapper as PrimitiveWheelPickerWrapper,
  type WheelPickerProps,
  type WheelPickerValue,
} from "@ncdai/react-wheel-picker";
import type { ComponentProps } from "react";
import styles from "./wheel-picker.module.css";

export function WheelPickerWrapper({ className, ...props }: ComponentProps<typeof PrimitiveWheelPickerWrapper>) {
  return <PrimitiveWheelPickerWrapper className={`${styles.wrapper} ${className ?? ""}`} {...props} />;
}

export function WheelPicker<T extends WheelPickerValue>({ classNames, ...props }: WheelPickerProps<T>) {
  return <PrimitiveWheelPicker
    classNames={{
      optionItem: `${styles.optionItem} ${classNames?.optionItem ?? ""}`,
      highlightWrapper: `${styles.highlightWrapper} ${classNames?.highlightWrapper ?? ""}`,
      highlightItem: `${styles.highlightItem} ${classNames?.highlightItem ?? ""}`,
    }}
    {...props}
  />;
}

export type { WheelPickerOption } from "@ncdai/react-wheel-picker";
