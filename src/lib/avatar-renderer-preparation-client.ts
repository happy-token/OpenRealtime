import type { AvatarDisplayConfig } from "@/components/digital-human/types";
import { resolveAvatarRendererBinding } from "./avatar-renderer-preparation";
import { readJsonResponse } from "./http-json-response";

export interface AvatarPreparationResponse {
  state?: "idle" | "preparing" | "ready" | "failed";
  progress?: number;
  taskId?: string;
  rendererAssetId?: string;
  error?: string;
}

interface AvatarPreparationOptions {
  request?: typeof fetch;
  signal?: AbortSignal;
  onProgress?: (progress: number) => void;
  wait?: (durationMs: number, signal?: AbortSignal) => Promise<void>;
  sourceImage?: Blob;
}

export async function readAvatarRendererPreparationState(
  displayConfig: AvatarDisplayConfig,
  {
    request = fetch,
    signal,
  }: Pick<AvatarPreparationOptions, "request" | "signal"> = {},
): Promise<AvatarPreparationResponse> {
  const binding = resolveAvatarRendererBinding(displayConfig);
  if (!binding) return { state: "idle", progress: 0 };
  const query = new URLSearchParams({
    rendererAssetId: binding.rendererAssetId,
    avatarId: binding.avatarId,
    avatarActionId: binding.avatarActionId,
  });
  const response = await request(`/api/avatar-renderer/preparations?${query}`, {
    cache: "no-store",
    signal,
  });
  const payload = await readJsonResponse<AvatarPreparationResponse>(
    response,
    "口型资产状态读取失败",
  );
  if (!response.ok) throw new Error(payload.error ?? "口型资产状态读取失败");
  if (payload.state !== "idle" && payload.state !== "ready") {
    throw new Error("口型资产状态响应无效");
  }
  return payload;
}

export async function prepareAvatarRendererAsset(
  displayConfig: AvatarDisplayConfig,
  {
    request = fetch,
    signal,
    onProgress = () => {},
    wait = abortableDelay,
    sourceImage,
  }: AvatarPreparationOptions = {},
): Promise<AvatarPreparationResponse> {
  const uploadBody = sourceImage ? new FormData() : undefined;
  if (uploadBody && sourceImage) {
    uploadBody.set("config", JSON.stringify(displayConfig));
    uploadBody.set("source_image", sourceImage);
  }
  const response = await request("/api/avatar-renderer/preparations", {
    method: "POST",
    ...(uploadBody ? {} : { headers: { "Content-Type": "application/json" } }),
    body: uploadBody ?? JSON.stringify(displayConfig),
    cache: "no-store",
    signal,
  });
  let payload = await readJsonResponse<AvatarPreparationResponse>(
    response,
    "口型资产准备请求失败",
  );
  assertSuccessfulPreparationResponse(response, payload);
  if (payload.state === "ready") return payload;
  const binding = resolveAvatarRendererBinding(displayConfig);
  if (!payload.taskId || !payload.rendererAssetId || !binding) {
    throw new Error("口型资产准备任务响应无效");
  }

  // Progress responses intentionally contain only the latest state. Keep the
  // immutable task identity from creation instead of depending on every poll
  // response to repeat it.
  const taskId = payload.taskId;
  const rendererAssetId = payload.rendererAssetId;
  while (!signal?.aborted) {
    await wait(750, signal);
    const query = new URLSearchParams({
      taskId,
      rendererAssetId,
      avatarId: binding.avatarId,
      avatarActionId: binding.avatarActionId,
    });
    const statusResponse = await request(`/api/avatar-renderer/preparations?${query}`, {
      cache: "no-store",
      signal,
    });
    payload = await readJsonResponse<AvatarPreparationResponse>(
      statusResponse,
      "口型资产状态读取失败",
    );
    assertSuccessfulPreparationResponse(statusResponse, payload);
    onProgress(clampProgress(payload.progress));
    if (payload.state === "ready") return payload;
  }
  throw new DOMException("Aborted", "AbortError");
}

function assertSuccessfulPreparationResponse(
  response: Response,
  payload: AvatarPreparationResponse,
) {
  if (!response.ok || payload.state === "failed") {
    throw new Error(payload.error ?? "口型资产准备失败");
  }
  if (payload.state !== "preparing" && payload.state !== "ready") {
    throw new Error("口型资产准备响应无效");
  }
}

function clampProgress(progress: number | undefined) {
  return Math.max(0, Math.min(100, Math.round(progress ?? 0)));
}

function abortableDelay(durationMs: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const onAbort = () => {
      clearTimeout(timeout);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timeout = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, durationMs);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
