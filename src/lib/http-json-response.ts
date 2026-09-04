/**
 * Reads JSON without exposing the browser parser error when an HTTP endpoint
 * unexpectedly returns an HTML or plain-text error page.
 */
export async function readJsonResponse<T>(
  response: Response,
  requestFailureMessage: string,
): Promise<T> {
  const raw = await response.text();
  try {
    return JSON.parse(raw) as T;
  } catch {
    if (!response.ok) {
      throw new Error(`${requestFailureMessage}（HTTP ${response.status}）`);
    }
    const serviceName = requestFailureMessage.replace(/(?:请求)?失败$/, "");
    throw new Error(`${serviceName}返回了无法识别的响应`);
  }
}
