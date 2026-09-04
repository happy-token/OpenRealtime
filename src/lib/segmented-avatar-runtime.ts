import type { AvatarDisplayConfig } from "@/components/digital-human/types";
import { resolveAvatarRendererBinding } from "./avatar-renderer-preparation";

export interface SegmentedAvatarRuntime {
  renderer: "livetalking-wav2lip256" | "livetalking-wav2lip96";
  avatarId: string;
  displayName: string;
}

export function getSegmentedAvatarRuntime(
  displayConfig: AvatarDisplayConfig,
): SegmentedAvatarRuntime | null {
  const binding = resolveAvatarRendererBinding(displayConfig);
  return binding ? {
    renderer: binding.renderer,
    avatarId: binding.avatarId,
    displayName: binding.displayName,
  } : null;
}
