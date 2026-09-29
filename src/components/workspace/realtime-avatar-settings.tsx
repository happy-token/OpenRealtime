"use client";
import { useLanguage } from "@/components/language/language-provider";


import { BackLink } from "@/components/workspace/back-link";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, BookOpen, ChevronDown, GripHorizontal, MemoryStick, Play, Plus, Save, Settings2, Sparkles, Volume2, Wrench, X } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { VoiceSelector } from "@/components/voice/voice-selector";
import { PersonaChoiceGrid } from "@/components/roles/persona-choice-grid";
import { useOfficialRealtimeAvatars } from "@/hooks/use-official-realtime-avatars";
import type { PersonaSummary } from "@/lib/avatar-persona";
import { readHostedAvatarProfile, saveHostedAvatarProfile, type HostedAvatarProfile } from "@/lib/hosted-avatar-profile";
import { fetchTools } from "@/lib/tool-catalog-client";
import type { ToolRecord } from "@/lib/tool-records";
import type { KnowledgeDocument } from "@/lib/knowledge-catalog-repository";
import { readJsonResponse } from "@/lib/http-json-response";
import styles from "./realtime-avatar-settings.module.css";

type Module = "voice" | "persona" | "tools" | "knowledge";
type ResizeEdge = "left" | "right" | "top" | "bottom";
const RESIZE_EDGES: ResizeEdge[] = ["left", "right", "top", "bottom"];
const RESIZE_EDGE_LABELS: Record<ResizeEdge, string> = { left: "左", right: "右", top: "上", bottom: "下" };

export function RealtimeAvatarSettings({ avatarId }: { avatarId: string }) {
  const { t } = useLanguage();
  const router = useRouter();
  const { avatars, personalAvatars, configured, loading } = useOfficialRealtimeAvatars();
  const avatar = [...avatars, ...personalAvatars].find((item) => item.id === avatarId);
  const [profile, setProfile] = useState<HostedAvatarProfile | null>(null);
  const [personas, setPersonas] = useState<PersonaSummary[]>([]);
  const [tools, setTools] = useState<ToolRecord[]>([]);
  const [knowledgeDocuments, setKnowledgeDocuments] = useState<KnowledgeDocument[]>([]);
  const [knowledgeIds, setKnowledgeIds] = useState<string[]>([]);
  const [memoryEnabled, setMemoryEnabled] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [openModule, setOpenModule] = useState<Module | null>(null);
  const [panelPosition, setPanelPosition] = useState({ x: 0, y: 0 });
  const [panelSize, setPanelSize] = useState({ width: 520, height: 620 });
  const [dragging, setDragging] = useState(false);
  const [resizing, setResizing] = useState(false);
  const panelRef = useRef<HTMLElement>(null);
  const dragRef = useRef<{ pointerId: number; x: number; y: number; originX: number; originY: number; left: number; top: number; right: number; bottom: number } | null>(null);
  const resizeRef = useRef<{ pointerId: number; edge: ResizeEdge; x: number; y: number; width: number; height: number; originX: number; originY: number; maxWidth: number; maxHeight: number } | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (avatar) setProfile(readHostedAvatarProfile(avatar.id, avatar.displayName));
  }, [avatar]);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      fetch("/api/personas", { cache: "no-store", signal: controller.signal }).then((response) => response.ok ? response.json() as Promise<{ personas?: PersonaSummary[] }> : { personas: [] }),
      fetchTools(controller.signal).catch(() => []),
      fetch("/api/knowledge", { cache: "no-store", signal: controller.signal }).then((response) => response.ok ? response.json() as Promise<{ documents?: KnowledgeDocument[] }> : { documents: [] }),
      fetch(`/api/hosted-avatar-settings/${encodeURIComponent(avatarId)}`, { cache: "no-store", signal: controller.signal }).then((response) => response.ok ? response.json() as Promise<{ documentIds?: string[]; memoryEnabled?: boolean }> : { documentIds: [], memoryEnabled: false }),
    ]).then(([payload, records, knowledge, settings]) => {
      if (!controller.signal.aborted) { setPersonas(payload.personas ?? []); setTools(records); setKnowledgeDocuments(knowledge.documents ?? []); setKnowledgeIds(settings.documentIds ?? []); setMemoryEnabled(settings.memoryEnabled ?? false); }
    }).catch(() => undefined);
    return () => controller.abort();
  }, [avatarId]);

  async function save(start: boolean) {
    if (!profile || !avatar) return;
    if (!profile.displayName.trim()) { setError("请填写名称"); return; }
    try {
      const response = await fetch(`/api/hosted-avatar-settings/${encodeURIComponent(avatar.id)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ memoryEnabled, documentIds: knowledgeIds, toolIds: profile.toolIds }),
      });
      const payload = await readJsonResponse<{ error?: string }>(response, "实时数字人配置保存失败");
      if (!response.ok) throw new Error(payload.error || "实时数字人配置保存失败");
      saveHostedAvatarProfile(avatar.id, { ...profile, displayName: profile.displayName.trim() });
      setError("");
      setNotice("配置已保存");
      if (start) router.push(`/conversation?realtime_avatar_id=${encodeURIComponent(avatar.id)}`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "实时数字人配置保存失败"); }
  }

  function startDrag(event: ReactPointerEvent<HTMLElement>) {
    if (window.innerWidth <= 760 || !panelRef.current || (event.target as HTMLElement).closest("button, input, label, a")) return;
    const rect = panelRef.current.getBoundingClientRect();
    dragRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, originX: panelPosition.x, originY: panelPosition.y,
      left: panelPosition.x - rect.left + 12, top: panelPosition.y - rect.top + 12,
      right: panelPosition.x + window.innerWidth - rect.right - 12, bottom: panelPosition.y + window.innerHeight - rect.bottom - 12 };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  }
  function moveDrag(event: ReactPointerEvent<HTMLElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    setPanelPosition({ x: Math.min(drag.right, Math.max(drag.left, drag.originX + event.clientX - drag.x)),
      y: Math.min(drag.bottom, Math.max(drag.top, drag.originY + event.clientY - drag.y)) });
  }
  function stopDrag(event: ReactPointerEvent<HTMLElement>) {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    dragRef.current = null; setDragging(false); event.currentTarget.releasePointerCapture(event.pointerId);
  }
  function startResize(event: ReactPointerEvent<HTMLDivElement>, edge: ResizeEdge) {
    if (window.innerWidth <= 760 || !panelRef.current) return;
    event.stopPropagation();
    const rect = panelRef.current.getBoundingClientRect();
    resizeRef.current = { pointerId: event.pointerId, edge, x: event.clientX, y: event.clientY, width: rect.width, height: rect.height,
      originX: panelPosition.x, originY: panelPosition.y,
      maxWidth: Math.min(window.innerWidth - 48, edge === "left" ? rect.right - 12 : window.innerWidth - rect.left - 12),
      maxHeight: Math.min(window.innerHeight - 108, edge === "top" ? rect.bottom - 12 : window.innerHeight - rect.top - 12) };
    event.currentTarget.setPointerCapture(event.pointerId); setResizing(true);
  }
  function moveResize(event: ReactPointerEvent<HTMLDivElement>) {
    const resize = resizeRef.current;
    if (!resize || resize.pointerId !== event.pointerId) return;
    const width = resize.edge === "left" ? Math.min(resize.maxWidth, Math.max(400, resize.width + resize.x - event.clientX))
      : resize.edge === "right" ? Math.min(resize.maxWidth, Math.max(400, resize.width + event.clientX - resize.x)) : resize.width;
    const height = resize.edge === "top" ? Math.min(resize.maxHeight, Math.max(320, resize.height + resize.y - event.clientY))
      : resize.edge === "bottom" ? Math.min(resize.maxHeight, Math.max(320, resize.height + event.clientY - resize.y)) : resize.height;
    setPanelSize({ width, height });
    if (resize.edge === "right") setPanelPosition((position) => ({ ...position, x: resize.originX + width - resize.width }));
    if (resize.edge === "top") setPanelPosition((position) => ({ ...position, y: resize.originY + resize.height - height }));
  }
  function stopResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (resizeRef.current?.pointerId !== event.pointerId) return;
    resizeRef.current = null; setResizing(false); event.currentTarget.releasePointerCapture(event.pointerId);
  }
  function resizeWithKeyboard(event: ReactKeyboardEvent<HTMLDivElement>, edge: ResizeEdge) {
    if (window.innerWidth <= 760 || !panelRef.current) return;
    const delta = event.shiftKey ? 64 : 24;
    const widthDelta = edge === "left" ? event.key === "ArrowLeft" ? delta : event.key === "ArrowRight" ? -delta : 0
      : edge === "right" ? event.key === "ArrowRight" ? delta : event.key === "ArrowLeft" ? -delta : 0 : 0;
    const heightDelta = edge === "top" ? event.key === "ArrowUp" ? delta : event.key === "ArrowDown" ? -delta : 0
      : edge === "bottom" ? event.key === "ArrowDown" ? delta : event.key === "ArrowUp" ? -delta : 0 : 0;
    if (!widthDelta && !heightDelta) return;
    event.preventDefault();
    const rect = panelRef.current.getBoundingClientRect();
    const width = Math.min(window.innerWidth - 48, edge === "left" ? rect.right - 12 : window.innerWidth - rect.left - 12, Math.max(400, rect.width + widthDelta));
    const height = Math.min(window.innerHeight - 108, edge === "top" ? rect.bottom - 12 : window.innerHeight - rect.top - 12, Math.max(320, rect.height + heightDelta));
    setPanelSize({ width, height });
    if (edge === "right") setPanelPosition((position) => ({ ...position, x: position.x + width - rect.width }));
    if (edge === "top") setPanelPosition((position) => ({ ...position, y: position.y + rect.height - height }));
  }
  function toggleModule(module: Module) { setOpenModule((current) => current === module ? null : module); }

  if (loading) return <p className={styles.status}>{t("正在读取实时数字人…")}</p>;
  if (!configured || !avatar) return <div className={styles.status}>{t("当前形象不可用或尚未配置 Anam。")}<BackLink href="/resources?tab=official-realtime" label={t("返回资源库")} /></div>;
  if (!profile) return null;
  return <main className={styles.page}>
    <div className={styles.stage}>
      {avatar.imageUrl ? <Image src={avatar.imageUrl} alt="" fill sizes="100vw" unoptimized /> : null}
      <div className={styles.stageShade} />
      <div className={styles.stageTitle}><h1>{profile.displayName}</h1><p>{avatar.origin === "official" ? t("官方") : t("我的")}{t("实时数字人 · 对话配置")}</p></div>
    </div>
    <header className={styles.topbar}>
      <Link href="/resources?tab=official-realtime" aria-label={t("返回实时数字人")}><ArrowLeft /></Link>
      <strong>{t("实时数字人")}</strong>
      <div><button type="button" aria-label={t("打开角色设置")} aria-expanded={panelOpen} onClick={() => setPanelOpen((open) => !open)}><Settings2 />{t("角色设置")}</button><button type="button" onClick={() => void save(true)}><Play />{t("开始对话")}</button></div>
    </header>
    <aside ref={panelRef} className={styles.panel} data-open={panelOpen} data-dragging={dragging} data-resizing={resizing} aria-label={t("角色设置")} aria-hidden={!panelOpen} inert={!panelOpen}
      style={{ "--panel-x": `${panelPosition.x}px`, "--panel-y": `${panelPosition.y}px`, "--panel-width": `${panelSize.width}px`, "--panel-height": `${panelSize.height}px` } as CSSProperties}>
      <header className={styles.panelHead} onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={stopDrag} onPointerCancel={stopDrag}>
        <GripHorizontal aria-hidden="true" /><div><h2>{t("角色设置")}</h2></div><button type="button" aria-label={t("关闭角色设置")} onClick={() => setPanelOpen(false)}><X /></button>
      </header>
      <div className={styles.panelBody}>
        <SettingsModule title={t("声音")} detail={profile.voiceId} icon={<Volume2 />} open={openModule === "voice"} onToggle={() => toggleModule("voice")}><VoiceSelector showCurrent={false} value={{ provider: profile.voiceProvider, voice: profile.voiceId, dialect: profile.voiceDialect }} onChange={(voice) => setProfile({ ...profile, voiceProvider: voice.provider, voiceId: voice.voice, voiceDialect: voice.dialect })} onSelectionCommit={() => setOpenModule(null)} allowClone allowManagement={false} /></SettingsModule>
        <SettingsModule title="Persona" detail={personas.find((item) => item.personaId === profile.personaId)?.personaName ?? "默认助手"} icon={<Sparkles />} open={openModule === "persona"} onToggle={() => toggleModule("persona")}><PersonaChoiceGrid personas={personas} value={profile.personaId} onChange={(personaId) => setProfile({ ...profile, personaId })} /><div className={styles.moduleToolbar}><span>{t("选择对话风格")}</span><Link href="/resources?tab=personas"><Plus />{t("新建人设")}</Link></div></SettingsModule>
        <SettingsModule title={t("工具")} detail={`已选择 ${profile.toolIds.length} 个`} icon={<Wrench />} open={openModule === "tools"} onToggle={() => toggleModule("tools")}><div className={styles.moduleToolbar}><span>{t("选择对话时可调用的工具")}</span><Link href="/resources?tab=tools"><Plus />{t("新建")}</Link></div><div className={styles.toolList} aria-label={t("角色工具")}>{tools.map((tool) => {
          const disabled = !tool.enabled || (!tool.builtin && !tool.endpoint);
          return <label key={tool.tool_id} data-disabled={disabled}><input type="checkbox" disabled={disabled} checked={profile.toolIds.includes(tool.tool_id)} onChange={(event) => setProfile({ ...profile, toolIds: event.target.checked ? [...profile.toolIds, tool.tool_id] : profile.toolIds.filter((id) => id !== tool.tool_id) })} /><span><strong>{tool.display_name}</strong><small>{disabled ? t("需要补充服务地址后才能执行") : tool.description}</small></span><em>{tool.builtin ? t("内置") : tool.public_enabled ? t("共享") : t("个人")}</em></label>;
        })}</div></SettingsModule>
        <SettingsModule title={t("知识库")} detail={knowledgeIds.length ? `已选择 ${knowledgeIds.length} 份` : "暂未选择"} icon={<BookOpen />} open={openModule === "knowledge"} onToggle={() => toggleModule("knowledge")}><div className={styles.moduleToolbar}><span>{t("选择对话时可检索的资料")}</span><Link href="/resources?tab=knowledge"><Plus />{t("新建")}</Link></div><div className={styles.toolList} aria-label={t("角色知识库资料")}>{knowledgeDocuments.map((document) => <label key={document.document_id}><input type="checkbox" checked={knowledgeIds.includes(document.document_id)} onChange={(event) => setKnowledgeIds((ids) => event.target.checked ? [...ids, document.document_id] : ids.filter((id) => id !== document.document_id))} /><span><strong>{document.title}</strong><small>{document.source_url ? t("包含外部来源") : t("本地资料")}</small></span><em>{document.owner_id === null ? t("共享") : t("个人")}</em></label>)}</div>{knowledgeDocuments.length === 0 ? <p>{t("暂无可用资料，请先到资源库创建知识库内容。")}</p> : null}</SettingsModule>
        <label className={styles.memorySwitch}><MemoryStick aria-hidden="true" /><span><strong>{t("长期记忆")}</strong><small>{t("仅用于这个实时数字人的对话")}</small></span><input type="checkbox" checked={memoryEnabled} onChange={(event) => setMemoryEnabled(event.target.checked)} aria-label={t("启用长期记忆")} /></label>
        {error ? <p role="alert" className={styles.error}>{t(error)}</p> : null}
        {notice ? <p role="status" className={styles.notice}>{t(notice)}</p> : null}
      </div>
      <footer className={styles.panelFooter}><button type="button" onClick={() => void save(false)}><Save />{t("保存配置")}</button></footer>
      {RESIZE_EDGES.map((edge) => <div key={edge} className={styles.resizeEdge} data-edge={edge} role="separator" aria-orientation={edge === "left" || edge === "right" ? "vertical" : "horizontal"} aria-label={t("拖动") + (RESIZE_EDGE_LABELS[edge]) + t("侧边缘调整窗口大小")} tabIndex={0} onPointerDown={(event) => startResize(event, edge)} onPointerMove={moveResize} onPointerUp={stopResize} onPointerCancel={stopResize} onKeyDown={(event) => resizeWithKeyboard(event, edge)} />)}
    </aside>
  </main>;
}

function SettingsModule({ title, detail, icon, open, onToggle, children }: { title: string; detail: string; icon: ReactNode; open: boolean; onToggle: () => void; children: ReactNode }) {
  return <section className={styles.module} data-open={open}><button type="button" className={styles.moduleToggle} aria-expanded={open} onClick={onToggle}>{icon}<span><strong>{title}</strong><small>{detail}</small></span><ChevronDown aria-hidden="true" /></button>{open ? <div className={styles.moduleContent}>{children}</div> : null}</section>;
}
