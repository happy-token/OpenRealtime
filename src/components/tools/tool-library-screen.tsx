"use client";

import { Braces, Check, ChevronRight, Cloud, LoaderCircle, Pencil, Plus, Server, Wrench, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { createTool, fetchTools, setToolEnabled, setToolPublicEnabled, updateTool } from "@/lib/tool-catalog-client";
import { TOOL_KIND_LABELS, type ToolKind, type ToolRecord } from "@/lib/tool-records";
import styles from "./tool-library-screen.module.css";

type EditableKind = Exclude<ToolKind, "builtin">;

const TEMPLATES: Array<{
  kind: EditableKind;
  title: string;
  description: string;
  functionName: string;
  endpoint: string;
  schema: Record<string, unknown>;
}> = [
  {
    kind: "function",
    title: "查询订单",
    description: "按订单号读取订单状态。",
    functionName: "get_order_status",
    endpoint: "http://127.0.0.1:3001/functions/get_order_status",
    schema: { type: "object", properties: { order_id: { type: "string", description: "订单号" } }, required: ["order_id"] },
  },
  {
    kind: "api",
    title: "天气 API",
    description: "调用 HTTP API 查询城市天气。",
    functionName: "get_weather",
    endpoint: "https://api.example.com/weather",
    schema: { type: "object", properties: { city: { type: "string", description: "城市" } }, required: ["city"] },
  },
  {
    kind: "mcp",
    title: "MCP 服务",
    description: "连接 Streamable HTTP MCP 服务并导入工具。",
    functionName: "get_weather",
    endpoint: "http://127.0.0.1:3001/mcp",
    schema: { type: "object", properties: {} },
  },
];

export function ToolLibraryScreen({ onCreated }: { onCreated?: () => void } = {}) {
  const [tools, setTools] = useState<ToolRecord[] | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [kind, setKind] = useState<EditableKind>("function");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [functionName, setFunctionName] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [method, setMethod] = useState<"GET" | "POST">("POST");
  const [riskLevel, setRiskLevel] = useState<NonNullable<ToolRecord["risk_level"]>>("medium");
  const [effect, setEffect] = useState<NonNullable<ToolRecord["effect"]>>("read_sensitive");
  const [schema, setSchema] = useState(JSON.stringify({ type: "object", properties: {} }, null, 2));

  useEffect(() => {
    const controller = new AbortController();
    void fetchTools(controller.signal).then(setTools).catch((cause) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "工具目录读取失败");
    });
    return () => controller.abort();
  }, []);

  const groups = useMemo(() => {
    const records = tools ?? [];
    return (["builtin", "function", "api", "mcp"] as const).map((groupKind) => ({
      kind: groupKind,
      tools: records.filter((tool) => tool.kind === groupKind),
    })).filter((group) => group.tools.length);
  }, [tools]);

  function applyTemplate(template: (typeof TEMPLATES)[number]) {
    setEditingId(null);
    setKind(template.kind);
    setDisplayName(template.title);
    setDescription(template.description);
    setFunctionName(template.functionName);
    setEndpoint(template.endpoint);
    setRiskLevel("medium");
    setEffect(template.kind === "api" ? "read_public" : "read_sensitive");
    setSchema(JSON.stringify(template.schema, null, 2));
    setCreating(true);
    setError("");
  }

  async function submit() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const inputSchema = JSON.parse(schema) as unknown;
      if (!inputSchema || typeof inputSchema !== "object" || Array.isArray(inputSchema)) throw new Error("输入 Schema 必须是 JSON 对象");
      const input = {
        displayName,
        description,
        kind,
        functionName,
        inputSchema: inputSchema as Record<string, unknown>,
        endpoint,
        method,
        riskLevel,
        effect,
      };
      const tool = editingId
        ? await updateTool(editingId, input)
        : await createTool({ ...input, mcpTransport: kind === "mcp" ? "streamable-http" : null });
      if (!editingId && onCreated) {
        onCreated();
        return;
      }
      setTools((current) => editingId ? (current ?? []).map(item => item.tool_id === editingId ? tool : item) : [...(current ?? []), tool]);
      setCreating(false);
      setEditingId(null);
      resetDraft();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "工具创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function toggle(tool: ToolRecord) {
    if (tool.builtin) return;
    setError("");
    try {
      const updated = await setToolEnabled(tool.tool_id, !tool.enabled);
      setTools((current) => current?.map((item) => item.tool_id === updated.tool_id ? updated : item) ?? []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "工具更新失败");
    }
  }

  async function togglePublic(tool: ToolRecord) {
    if (tool.builtin) return;
    setError("");
    try {
      const updated = await setToolPublicEnabled(tool.tool_id, !tool.public_enabled);
      setTools(current => current?.map(item => item.tool_id === updated.tool_id ? updated : item) ?? []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "公开工具状态更新失败");
    }
  }

  function resetDraft() {
    setDisplayName("");
    setDescription("");
    setFunctionName("");
    setEndpoint("");
    setSchema(JSON.stringify({ type: "object", properties: {} }, null, 2));
    setRiskLevel("medium");
    setEffect("read_sensitive");
  }

  function edit(tool: ToolRecord) {
    if (tool.builtin) return;
    setEditingId(tool.tool_id);
    setKind(tool.kind as EditableKind);
    setDisplayName(tool.display_name);
    setDescription(tool.description);
    setFunctionName(tool.function_name);
    setEndpoint(tool.endpoint ?? "");
    setMethod(tool.method ?? "POST");
    setRiskLevel(tool.risk_level ?? "medium");
    setEffect(tool.effect ?? "read_sensitive");
    setSchema(JSON.stringify(tool.input_schema, null, 2));
    setCreating(true);
    setError("");
  }

  return <div className={styles.page}>
    <div className={styles.heading}><div><h2>工具</h2><p>Function Calling、HTTP API 与 MCP 统一为角色可绑定的工具。</p></div><button type="button" onClick={() => { setEditingId(null); resetDraft(); setCreating(true); }}><Plus />新建工具</button></div>

    <section className={styles.templates} aria-label="工具示例">
      {TEMPLATES.map((template) => <button key={template.kind} type="button" onClick={() => applyTemplate(template)}>{toolIcon(template.kind)}<span><strong>{template.title}</strong><small>{TOOL_KIND_LABELS[template.kind]} 示例</small></span><ChevronRight /></button>)}
    </section>

    {creating ? <section className={styles.editor} aria-label="新建工具">
      <header><div><span>{editingId ? "EDIT TOOL" : "NEW TOOL"}</span><h3>{editingId ? "编辑工具" : "新建工具"}</h3></div><button type="button" aria-label="关闭" onClick={() => setCreating(false)}><X /></button></header>
      <div className={styles.kindTabs}>{(["function", "api", "mcp"] as const).map((item) => <button key={item} type="button" data-active={kind === item} onClick={() => setKind(item)}>{TOOL_KIND_LABELS[item]}</button>)}</div>
      <div className={styles.fields}>
        <label><span>名称</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="例如：查询订单" /></label>
        <label><span>函数名称</span><input value={functionName} onChange={(event) => setFunctionName(event.target.value)} placeholder="get_order_status" /></label>
        <label className={styles.wide}><span>说明</span><input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="告诉模型何时使用这个工具" /></label>
        <label className={styles.wide}><span>{kind === "mcp" ? "Streamable HTTP 服务地址" : kind === "function" ? "函数执行服务地址" : "API 地址"}</span><input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} placeholder={kind === "mcp" ? "http://127.0.0.1:3001/mcp" : "https://api.example.com/action"} /></label>
        {kind === "api" ? <label><span>请求方法</span><select value={method} onChange={(event) => setMethod(event.target.value === "GET" ? "GET" : "POST")}><option>GET</option><option>POST</option></select></label> : null}
        <label><span>风险等级</span><select value={riskLevel} onChange={(event) => setRiskLevel(event.target.value as NonNullable<ToolRecord["risk_level"]>)}><option value="low">低</option><option value="medium">中</option><option value="high">高 · 强确认</option><option value="critical">极高 · 禁止语音调用</option></select></label>
        <label><span>工具作用</span><select value={effect} onChange={(event) => setEffect(event.target.value as NonNullable<ToolRecord["effect"]>)}><option value="read_public">读取公开信息</option><option value="read_sensitive">读取敏感信息</option><option value="write_reversible">可撤销写入</option><option value="write_irreversible">不可撤销写入</option><option value="execute_code">执行代码</option><option value="communicate_external">对外通信</option><option value="spend_or_transfer">支付或转账</option><option value="control_device">控制设备</option></select></label>
        {kind === "mcp" ? <p>当前支持 Streamable HTTP；函数名称填写服务端已有的工具名称。</p> : null}
        <p className={styles.wide}>工具服务来源须由管理员允许；保存后重新进入对话才会加载。</p>
        <label className={styles.wide}><span>输入 Schema</span><textarea value={schema} onChange={(event) => setSchema(event.target.value)} spellCheck={false} /></label>
      </div>
      <footer><button type="button" data-secondary="true" onClick={() => setCreating(false)}>取消</button><button type="button" disabled={busy} onClick={() => void submit()}>{busy ? <LoaderCircle className={styles.spin} /> : <Check />}保存工具</button></footer>
    </section> : null}

    {error ? <p className={styles.error} role="alert">{error}</p> : null}
    {tools === null && !error ? <div className={styles.loading}><LoaderCircle className={styles.spin} />正在读取工具目录</div> : null}
    {groups.map((group) => <section className={styles.group} key={group.kind}><header><strong>{TOOL_KIND_LABELS[group.kind]}</strong><span>{group.tools.length} 个</span></header><div>{group.tools.map((tool) => <article key={tool.tool_id} data-enabled={tool.enabled}>{toolIcon(tool.kind)}<div><strong>{tool.display_name}</strong><small>{tool.description}</small><code>{tool.function_name}</code></div><span className={styles.actions}>{!tool.builtin ? <button type="button" className={styles.editAction} aria-label={`编辑工具${tool.display_name}`} title="编辑工具" onClick={() => edit(tool)}><Pencil /></button> : null}{!tool.builtin ? <button type="button" disabled={!tool.endpoint || !tool.enabled} aria-label={`${tool.public_enabled ? "关闭" : "允许"}${tool.display_name}公开语音使用`} onClick={() => void togglePublic(tool)}>{tool.public_enabled ? "公开可用" : "仅内部"}</button> : null}<button type="button" disabled={tool.builtin} aria-label={`${tool.enabled ? "停用" : "启用"}${tool.display_name}`} onClick={() => void toggle(tool)}>{tool.builtin ? "内置" : tool.enabled ? "已启用" : "已停用"}</button></span></article>)}</div></section>)}
  </div>;
}

function toolIcon(kind: ToolKind) {
  if (kind === "mcp") return <Server />;
  if (kind === "api") return <Cloud />;
  if (kind === "function") return <Braces />;
  return <Wrench />;
}
