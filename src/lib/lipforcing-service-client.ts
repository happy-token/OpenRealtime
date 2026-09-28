type Fetcher = typeof fetch;

type LipForcingServiceJob = {
  id?: string;
  state?: "queued" | "processing" | "success" | "failed";
  error?: string;
  detail?: string;
};

export type LipForcingServiceJobInput = {
  baseUrl: string;
  token?: string;
  jobId: string;
  sourceVideo: Buffer;
  referenceAudio: Buffer;
  rightsConfirmed?: boolean;
  usageScope?: string;
  sourceField?: string;
  referenceField?: string;
  sourceName?: string;
  referenceName?: string;
  sourceType?: string;
  referenceType?: string;
  configJson?: string;
  fetcher?: Fetcher;
  pollIntervalMs?: number;
  retryDelayMs?: number;
  timeoutMs?: number;
};

export async function runInferenceServiceJob(input: LipForcingServiceJobInput): Promise<Buffer> {
  const baseUrl = normalizeBaseUrl(input.baseUrl);
  const fetcher = input.fetcher ?? fetch;
  const headers: Record<string, string> = {};
  if (input.token) headers.Authorization = `Bearer ${input.token}`;
  const form = new FormData();
  form.set(input.sourceField ?? "source_video", new Blob([new Uint8Array(input.sourceVideo)], { type: input.sourceType ?? "video/mp4" }), input.sourceName ?? "source.mp4");
  form.set(input.referenceField ?? "reference_audio", new Blob([new Uint8Array(input.referenceAudio)], { type: input.referenceType ?? "audio/wav" }), input.referenceName ?? "reference.wav");
  if (input.rightsConfirmed) form.set("rights_confirmed", "true");
  if (input.usageScope) form.set("usage_scope", input.usageScope);
  if (input.configJson) form.set("config_json", input.configJson);
  const submitted = await fetcher(`${baseUrl}/v1/jobs`, {
    method: "POST",
    headers: { ...headers, "X-Job-Id": input.jobId },
    body: form,
    signal: AbortSignal.timeout(120_000),
    cache: "no-store", redirect: "manual",
  });
  const created = await readJobResponse(submitted, "Lip Forcing GPU 任务提交失败");
  if (!submitted.ok || !created.id) throw new Error(created.detail || created.error || "Lip Forcing GPU 任务提交失败");

  const pollIntervalMs = input.pollIntervalMs ?? 2_000;
  const deadline = Date.now() + (input.timeoutMs ?? 3_660_000);
  let job = created;
  while (job.state === "queued" || job.state === "processing") {
    if (Date.now() >= deadline) throw new Error("Lip Forcing GPU 任务等待超时");
    if (pollIntervalMs > 0) await delay(pollIntervalMs);
    const response = await fetchWithRetry(fetcher, `${baseUrl}/v1/jobs/${encodeURIComponent(created.id)}`, { headers, cache: "no-store", redirect: "manual" }, input.retryDelayMs ?? 1_000);
    job = await readJobResponse(response, "Lip Forcing GPU 任务状态读取失败");
    if (!response.ok) throw new Error(job.detail || job.error || "Lip Forcing GPU 任务状态读取失败");
  }
  if (job.state !== "success") throw new Error(job.error || "Lip Forcing GPU 推理失败");

  const result = await fetchWithRetry(fetcher, `${baseUrl}/v1/jobs/${encodeURIComponent(created.id)}/result`, { headers, cache: "no-store", redirect: "manual" }, input.retryDelayMs ?? 1_000);
  if (!result.ok) throw new Error("Lip Forcing GPU 结果下载失败");
  const output = Buffer.from(await result.arrayBuffer());
  if (!output.length) throw new Error("Lip Forcing GPU 返回了空结果");
  return output;
}

export const runLipForcingServiceJob = runInferenceServiceJob;

function normalizeBaseUrl(value: string) {
  const url = new URL(value);
  if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("Lip Forcing API URL 必须使用 HTTP(S)");
  return url.toString().replace(/\/$/, "");
}

async function readJobResponse(response: Response, fallback: string): Promise<LipForcingServiceJob> {
  try {
    return await response.json() as LipForcingServiceJob;
  } catch {
    throw new Error(fallback);
  }
}

function delay(milliseconds: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
}

async function fetchWithRetry(fetcher: Fetcher, url: string, init: RequestInit, retryDelayMs: number): Promise<Response> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fetcher(url, { ...init, signal: AbortSignal.timeout(120_000) });
    } catch (error) {
      if (!(error instanceof TypeError) || attempt >= 5) throw error;
      if (retryDelayMs > 0) await delay(retryDelayMs * 2 ** attempt);
    }
  }
}
