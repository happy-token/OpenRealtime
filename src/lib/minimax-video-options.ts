export const MINIMAX_RATIOS = ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"] as const;
export const MINIMAX_RESOLUTIONS = ["480P", "768P", "2K"] as const;
export const MINIMAX_DURATIONS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] as const;

export type MiniMaxRatio = (typeof MINIMAX_RATIOS)[number];
export type MiniMaxResolution = (typeof MINIMAX_RESOLUTIONS)[number];
export type MiniMaxDuration = (typeof MINIMAX_DURATIONS)[number];
export type MiniMaxImageRole =
  | "first_and_last_frame"
  | "first_frame"
  | "last_frame"
  | "reference_image";
