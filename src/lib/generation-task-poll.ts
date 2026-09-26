type GenerationTaskState = "queueing" | "processing" | "success" | "failed";

type GenerationTaskPayload = {
  state?: GenerationTaskState;
  result_url?: string;
  error?: string;
};

export type GenerationTaskPollResult =
  | { kind: "state"; state: GenerationTaskState; resultUrl?: string; message?: string }
  | { kind: "retry"; message: string }
  | { kind: "failed"; message: string };

export async function pollRecoverableGenerationTask(
  endpoint: string,
  fetcher: typeof fetch = fetch,
  signal?: AbortSignal,
): Promise<GenerationTaskPollResult> {
  try {
    const response = await fetcher(endpoint, { cache: "no-store", signal });
    const payload = await response.json().catch(() => ({})) as GenerationTaskPayload;
    if (!response.ok) {
      const message = payload.error || "视频生成状态读取失败";
      if (response.status === 408 || response.status === 425 || response.status === 429 || response.status >= 500) {
        return { kind: "retry", message };
      }
      return { kind: "failed", message };
    }
    const state = payload.state;
    if (!state) return { kind: "retry", message: "视频生成状态响应暂时不可用" };
    if (state === "failed") return { kind: "failed", message: payload.error || "动作生成失败" };
    return { kind: "state", state, resultUrl: payload.result_url, message: payload.error };
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    return { kind: "retry", message: "视频生成状态暂时无法读取" };
  }
}
