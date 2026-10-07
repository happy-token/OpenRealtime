/** Compare Origin with the actual HTTP authority; never trust forwarded headers. */
export function isSameOriginRequest(request: Request): boolean {
  try {
    const url = new URL(request.url), host = request.headers.get("host");
    // Next may normalize 127.0.0.1 to localhost in the request URL.
    if (host !== null && !/^(?:[A-Za-z0-9.-]+|\[[A-Fa-f0-9:]+\])(?::[0-9]+)?$/.test(host)) return false;
    const expected = host === null ? url.origin : new URL(`${url.protocol}//${host}`).origin;
    const origin = request.headers.get("origin"), site = request.headers.get("sec-fetch-site");
    return Boolean(origin && origin === expected && (!site || site === "same-origin"));
  } catch { return false; }
}
