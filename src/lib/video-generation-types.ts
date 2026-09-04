import type { VideoGenerationModelId } from "./ltx-avatar-action";

export type VideoGenerationTaskState = "queueing" | "processing" | "success" | "failed";

export type VideoGenerationTask = {
  taskId: string;
  state: VideoGenerationTaskState;
  model: VideoGenerationModelId;
  createdAt: string;
};

export type VideoGenerationStatus = {
  taskId: string;
  state: VideoGenerationTaskState;
  videoUrl?: string;
  error?: string;
};
