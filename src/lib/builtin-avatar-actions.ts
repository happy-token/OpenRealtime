import { LIVEPORTRAIT_ACTIONS } from "./liveportrait-actions";

export type BuiltinAvatarAction = {
  id: `builtin:${string}`;
  avatarId: string;
  name: string;
  videoUrl: string;
  previewImageUrl?: string;
};

export const SAMANTHA_AVATAR_ID = "avatar-8657be31-306e-428d-a013-7521e710ab6a";

export const BUILTIN_AVATAR_ACTIONS: readonly BuiltinAvatarAction[] = [
  {
    id: "builtin:shuchang-realtime-idle",
    avatarId: "shuchang",
    name: "实时待机",
    videoUrl: "/digital-human/builtin-motion/shuchang-realtime-idle.mp4",
    previewImageUrl: "/digital-human/shuchang-preview.jpg",
  },
  ...LIVEPORTRAIT_ACTIONS.map((action) => ({
    id: `builtin:liveportrait:${action.id}` as const,
    avatarId: SAMANTHA_AVATAR_ID,
    name: action.name,
    videoUrl: action.referenceVideoUrl,
  })),
];

export function getBuiltinAvatarAction(actionId: string): BuiltinAvatarAction | undefined {
  return BUILTIN_AVATAR_ACTIONS.find((action) => action.id === actionId);
}
