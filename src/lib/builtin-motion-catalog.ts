import { getBuiltinAvatarAction } from "./builtin-avatar-actions";

export const BUILTIN_MOTION_PREVIEW_URLS = {
  "avatar-bundled": "/digital-human/builtin-motion/avatar-bundled.mp4",
  "ffmpeg-static": "/digital-human/builtin-motion/ffmpeg-static.mp4",
  "liveportrait-optimized": "/digital-human/builtin-motion/liveportrait-optimized.mp4",
} as const satisfies Record<string, string>;

export type BuiltinMotionId = keyof typeof BUILTIN_MOTION_PREVIEW_URLS;

export const BUILTIN_MOTION_POSTER_URLS = {
  "avatar-bundled": "/digital-human/builtin-motion/avatar-bundled.jpg",
  "ffmpeg-static": "/digital-human/builtin-motion/ffmpeg-static.jpg",
  "liveportrait-optimized": "/digital-human/builtin-motion/liveportrait-optimized.jpg",
} as const satisfies Record<BuiltinMotionId, string>;

export function getBuiltinMotionPreviewUrl(motionId: string) {
  return getBuiltinAvatarAction(`builtin:${motionId}`)?.videoUrl
    ?? BUILTIN_MOTION_PREVIEW_URLS[motionId as BuiltinMotionId];
}

export function getBuiltinMotionPosterUrl(motionId: string) {
  return BUILTIN_MOTION_POSTER_URLS[motionId as BuiltinMotionId];
}
