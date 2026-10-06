import { isPersonalTalkingKind } from "./user-talking-model-services";

export function isPersonalModelKind(value: unknown): value is "lipforcing" | "musetalk" | "wav2lip" {
  return value === "lipforcing" || isPersonalTalkingKind(value);
}
