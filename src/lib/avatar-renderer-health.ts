import { resolveAvatarRendererRuntime } from "./avatar-renderer-runtime";

/** Readiness probe only. It must not start the managed renderer. */
export async function avatarRendererIsReady(
  env: Record<string, string | undefined> = process.env,
  fetcher: typeof fetch = fetch,
): Promise<boolean> {
  try {
    const runtime = resolveAvatarRendererRuntime(env);
    if (!runtime) return false;
    const url = runtime.mode === "managed" ? `${runtime.internalUrl}/health` : runtime.internalUrl;
    const response = await fetcher(url, {
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(1_500),
    });
    if (runtime.mode === "external") return response.ok || response.status === 302;
    if (!response.ok) return false;
    const health = await response.json() as { renderer?: string };
    return health.renderer === "openrealtime";
  } catch {
    return false;
  }
}
