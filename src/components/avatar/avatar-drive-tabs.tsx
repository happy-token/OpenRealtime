"use client";

import styles from "./avatar-studio.module.css";

export type AvatarCreationTask = "realtime" | "action" | "lightweight";
const DRIVE_OPTIONS = [['realtime', '实时托管'], ['action', '多段式合成'], ['lightweight', '动作编排']] as const;

export function AvatarDriveTabs({ value, onChange, disabled = false, tasks }: {
  value: AvatarCreationTask;
  onChange: (value: AvatarCreationTask) => void;
  disabled?: boolean;
  tasks?: readonly AvatarCreationTask[];
}) {
  return <div className={styles.driveTabs} role="group" aria-label="数字人驱动方式">
    {DRIVE_OPTIONS.filter(([id]) => !tasks || tasks.includes(id)).map(([id, label]) =>
      <button key={id} type="button" aria-pressed={value === id} disabled={disabled} onClick={() => onChange(id)}>{label}</button>)}
  </div>;
}
