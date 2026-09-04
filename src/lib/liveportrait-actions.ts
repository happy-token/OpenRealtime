export type LivePortraitActionId =
  | "sweet-vitality"
  | "soft-glow"
  | "cool-night"
  | "gentle-intellectual"
  | "melancholy-empathy";

export type LivePortraitAction = {
  id: LivePortraitActionId;
  name: string;
  description: string;
  duration: string;
  provenance: "project-preset" | "liveportrait-official";
  provenanceLabel: string;
  referenceVideoUrl: string;
  closedMouthSafe: boolean;
  caution?: string;
  source: {
    scope: "project" | "runtime";
    relativePath: string;
  };
};

const builtInAction = (
  id: LivePortraitActionId,
  name: string,
  description: string,
  duration: string,
  filename: string,
  closedMouthSafe = true,
  caution?: string,
): LivePortraitAction => {
  const referenceVideoUrl = `/digital-human/liveportrait-actions/${filename}`;
  return {
    id,
    name,
    description,
    duration,
    provenance: "project-preset",
    provenanceLabel: "内置动作参考",
    referenceVideoUrl,
    closedMouthSafe,
    ...(caution ? { caution } : {}),
    source: { scope: "project", relativePath: `public${referenceVideoUrl}` },
  };
};

export const LIVEPORTRAIT_ACTIONS: readonly LivePortraitAction[] = [
  builtInAction(
    "sweet-vitality",
    "甜美元气",
    "眉眼提亮与轻快肩部律动",
    "约 7 秒",
    "sweet-vitality.mp4",
  ),
  builtInAction("soft-glow", "纯欲柔光", "害羞眉眼与轻柔肩部收放", "约 7 秒", "soft-glow.mp4"),
  builtInAction("cool-night", "冷艳夜色", "稳定直视与克制眉眼强调", "约 7 秒", "cool-night.mp4"),
  builtInAction("gentle-intellectual", "知性温柔", "内眉安慰与稳定陪伴感", "约 7 秒", "gentle-intellectual.mp4"),
  builtInAction("melancholy-empathy", "忧郁共鸣", "夜晚独处、侧垂避视与脆弱停顿", "约 7 秒", "melancholy-empathy.mp4"),
] as const;

const ACTION_IDS = new Set(LIVEPORTRAIT_ACTIONS.map((action) => action.id));

export function getLivePortraitAction(value: unknown): LivePortraitAction | undefined {
  return typeof value === "string" ? LIVEPORTRAIT_ACTIONS.find((action) => action.id === value) : undefined;
}

export function isLivePortraitActionId(value: unknown): value is LivePortraitActionId {
  return typeof value === "string" && ACTION_IDS.has(value as LivePortraitActionId);
}
