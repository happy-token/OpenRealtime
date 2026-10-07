"use client";

import { useEffect, useRef, useState } from "react";

export function DiagnosticAgentAccess({ sessionId, preview = false }: { sessionId: string; preview?: boolean }) {
  const active = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => () => { active.current?.abort(); }, [sessionId]);
  const download = async () => {
    if (preview || active.current) return;
    const controller = new AbortController(); active.current = controller;
    const timeout = setTimeout(() => controller.abort(), 10_000);
    setBusy(true); setMessage("");
    try {
      const endpoint = `/api/observability/sessions/${encodeURIComponent(sessionId)}/diagnostics`;
      const response = await fetch(`${endpoint}/access`, { method: "POST", cache: "no-store", signal: controller.signal });
      const grant = await response.json();
      if (!response.ok) throw new Error(grant.error ?? "Agent 授权生成失败");
      if (controller.signal.aborted) return;
      const bundle = {
        ...grant, endpoint: new URL(endpoint, window.location.origin).href,
        method: "GET", authorization_header: `Bearer ${grant.access_token}`,
        pagination: { telemetry: "telemetry.next_cursor → telemetry_cursor", debug_log: "debug_log.next_cursor → debug_cursor" },
        instruction: "仅查询此 Session；凭据15分钟内有效。通过 Authorization 请求头使用，不要放入链接或日志。数据源缺失或截断必须保留说明。录音尚未接入。",
      };
      const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" }));
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${sessionId}-agent-access.json`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage(`已下载只读凭据，有效至 ${new Date(grant.expires_at).toLocaleTimeString()}。请将文件交给排查 Agent。`);
    } catch (error) {
      if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "Agent 授权生成失败");
      else if (active.current === controller) setMessage("授权请求已取消或超时，请重试。");
    } finally {
      clearTimeout(timeout);
      if (active.current === controller) { active.current = null; setBusy(false); }
    }
  };
  return <>
    <button disabled={preview || busy} onClick={download}>{busy ? "正在生成…" : "生成 Agent 只读凭据"}</button>
    {message ? <p role="status">{message}</p> : null}
    <p>凭据仅可读取当前会话，15 分钟后失效。{preview ? "预览页面不签发凭据。" : "由当前管理员授权。"}</p>
  </>;
}
