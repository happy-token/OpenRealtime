// The Web app stays on the ordinary Cloudflare-proxied origin. This Worker
// routes only /voice WebSocket upgrades to the separately hosted voice origin.
export default {
  async fetch(request, env) {
    const incoming = new URL(request.url);
    if (incoming.pathname !== "/voice") {
      return new Response("Not found", { status: 404 });
    }
    if (request.method !== "GET" || request.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
      return new Response("WebSocket upgrade required", { status: 426 });
    }

    let origin;
    try {
      origin = new URL(env.VOICE_ORIGIN);
    } catch {
      return new Response("Voice origin is not configured", { status: 503 });
    }
    if (
      origin.protocol !== "https:" ||
      origin.hostname.endsWith(".example.com") ||
      origin.hostname === incoming.hostname ||
      origin.pathname !== "/" ||
      origin.search ||
      origin.hash ||
      origin.username ||
      origin.password
    ) {
      return new Response("Voice origin is not configured", { status: 503 });
    }

    const target = new URL(incoming.pathname + incoming.search, origin);
    return fetch(new Request(target, request));
  },
};
