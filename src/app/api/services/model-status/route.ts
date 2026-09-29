import { modelServiceConnections, probeModelService } from "@/lib/model-service-connections";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const connections = await modelServiceConnections();
    const services = Object.fromEntries(await Promise.all(Object.entries(connections).map(async ([kind, connection]) => {
      const configured = Boolean(connection.url);
      const status = configured
        ? await probeModelService(kind as keyof typeof connections, connection)
        : { ready: false, message: "平台服务未配置" };
      return [kind, { configured, ready: status.ready, message: status.message }];
    })));
    return Response.json({ services }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: "无法读取平台模型服务状态" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
