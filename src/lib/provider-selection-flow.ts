import type { ProviderConnectionStatus } from "./provider-instances";

/** Complete the UI's select action without changing the server-side readiness rule. */
export async function selectProviderInstanceForUse(
  instanceId: string, status: ProviderConnectionStatus, fetcher: typeof fetch = fetch,
): Promise<{ tested: boolean }> {
  if (status !== "passed") {
    const testResponse = await fetcher(`/api/provider-instances/${instanceId}/test`, { method: "POST" });
    const test = await testResponse.json().catch(() => ({})) as { ok?: boolean; message?: string; error?: string };
    if (!testResponse.ok || test.ok !== true) throw new Error(test.message || test.error || "实时能力测试未通过");
  }
  const response = await fetcher(`/api/provider-instances/${instanceId}/select`, { method: "POST" });
  const payload = await response.json().catch(() => ({})) as { error?: string };
  if (!response.ok) throw new Error(payload.error || "切换供应商失败");
  return { tested: status !== "passed" };
}
