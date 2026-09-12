"use client";

import styles from "./avatar-studio.module.css";

export type AvatarCreationTask = "realtime" | "action" | "lightweight";
export function AvatarDriveTabs({ value, onChange, disabled = false }: {
  value: AvatarCreationTask;
  onChange: (value: AvatarCreationTask) => void;
  disabled?: boolean;
}) {
  return <div className={styles.driveTabs} role="group" aria-label="数字人驱动方式">
    {([['realtime', '实时托管'], ['action', '多段式合成'], ['lightweight', '动作编排']] as const).map(([id, label]) =>
      <button key={id} type="button" aria-pressed={value === id} disabled={disabled} onClick={() => onChange(id)}>{label}</button>)}
  </div>;
}
