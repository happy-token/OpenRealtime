import {
  isMiniMaxModelId,
  videoGenerationProviderForModel,
  type VideoGenerationModelId,
} from "./ltx-avatar-action";
import {
  createLtxImageToVideo,
  getLtxGeneration,
  LtxProviderError,
  ltxConfig,
  type LtxEnvironment,
} from "./ltx-video";
import {
  createMiniMaxImageToVideo,
  getMiniMaxGeneration,
  MiniMaxProviderError,
  miniMaxConfig,
  type MiniMaxDuration,
  type MiniMaxImageRole,
  type MiniMaxRatio,
  type MiniMaxReferenceVideo,
  type MiniMaxResolution,
  type MiniMaxEnvironment,
} from "./minimax-video";
import type { VideoGenerationStatus, VideoGenerationTask } from "./video-generation-types";

export type VideoGenerationEnvironment = LtxEnvironment & MiniMaxEnvironment;

export function assertVideoGenerationModelConfigured(
  environment: VideoGenerationEnvironment,
  model: VideoGenerationModelId,
) {
  return videoGenerationProviderForModel(model) === "minimax"
    ? miniMaxConfig(environment)
    : ltxConfig(environment);
}

export async function createImageToVideo(
  environment: VideoGenerationEnvironment,
  input: {
    imageDataUrl: string;
    prompt: string;
    model: VideoGenerationModelId;
    ratio?: MiniMaxRatio;
    resolution?: MiniMaxResolution;
    duration?: MiniMaxDuration;
    imageRole?: MiniMaxImageRole;
    referenceVideo?: MiniMaxReferenceVideo;
  },
): Promise<VideoGenerationTask> {
  if (isMiniMaxModelId(input.model)) {
    return createMiniMaxImageToVideo(environment, {
      ...input,
      model: input.model,
      ratio: input.ratio ?? "adaptive",
      resolution: input.resolution ?? "768P",
      duration: input.duration ?? 6,
      imageRole: input.imageRole ?? "first_and_last_frame",
    });
  }
  return createLtxImageToVideo(environment, { ...input, model: input.model });
}

export async function getVideoGeneration(
  environment: VideoGenerationEnvironment,
  taskId: string,
  model: VideoGenerationModelId,
): Promise<VideoGenerationStatus> {
  return isMiniMaxModelId(model)
    ? getMiniMaxGeneration(environment, taskId, model)
    : getLtxGeneration(environment, taskId);
}

export function isVideoGenerationProviderError(error: unknown): error is LtxProviderError | MiniMaxProviderError {
  return error instanceof LtxProviderError || error instanceof MiniMaxProviderError;
}
