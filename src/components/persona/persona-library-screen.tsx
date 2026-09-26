"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ChevronDown, FileText, Link2, Plus } from "lucide-react";
import type { AvatarPersonaFile, PersonaProfile, PersonaSummary } from "@/lib/avatar-persona";
import {
  buildPersonaSavePayload,
  buildPersonaSwitchPayload,
  isPersonaDraftDirty,
  personaDraftFromFiles,
} from "@/lib/persona-editor";
import { readJsonResponse } from "@/lib/http-json-response";
import styles from "./persona-library-screen.module.css";

type LoadState = "loading" | "loaded" | "error";
type ActionState = "idle" | "busy" | "done" | "error";

const CREATE_FIELDS = [
  ["SOUL.md", "SOUL", "人格、语气、价值观与关系边界", true],
  ["IDENTITY.md", "IDENTITY", "身份背景与自我定位", true],
  ["AGENTS.md", "AGENTS", "对话操作规则、能力边界与回复约束", false],
] as const;

/**
 * Strips any leading `# ...` heading the user may have typed into the
 * IDENTITY textarea, then prepends `# ${name}` so the persisted IDENTITY.md
 * always resolves to the name typed in the dedicated field.
 */
function withIdentityHeading(name: string, body: string): string {
  const rest = body.replace(/^#\s+.*(?:\r?\n+)?/, "").trimStart();
  return rest ? `# ${name.trim()}\n\n${rest}` : `# ${name.trim()}`;
}

export function PersonaLibraryScreen({
  linkingAvatarId,
  linkingAvatarDisplayName = "",
  onCreated,
  embedded = false,
}: {
  linkingAvatarId?: string;
  linkingAvatarDisplayName?: string;
  onCreated?: () => void;
  embedded?: boolean;
}) {
  const router = useRouter();
  const [personas, setPersonas] = useState<PersonaSummary[] | null>(null);
  const [listState, setListState] = useState<LoadState>("loading");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [profiles, setProfiles] = useState<Record<string, PersonaProfile>>({});
  const [profileState, setProfileState] = useState<Record<string, LoadState>>({});
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({});
  const [introDrafts, setIntroDrafts] = useState<Record<string, string>>({});
  const [saveState, setSaveState] = useState<Record<string, ActionState>>({});
  const [saveNotice, setSaveNotice] = useState<Record<string, string>>({});
  const [linkState, setLinkState] = useState<Record<string, ActionState>>({});
  const [linkNotice, setLinkNotice] = useState("");
  const [creating, setCreating] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createIntro, setCreateIntro] = useState("");
  const [createId, setCreateId] = useState("");
  const [createDraft, setCreateDraft] = useState<Record<string, string>>({});
  const [createState, setCreateState] = useState<ActionState>("idle");
  const [createNotice, setCreateNotice] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setListState("loading");
    void fetch("/api/personas", { cache: "no-store", signal: controller.signal })
      .then((response) => readJsonResponse<{ personas?: PersonaSummary[] }>(response, "Persona 列表读取失败"))
      .then((payload) => {
        setPersonas(payload.personas ?? []);
        setListState("loaded");
      })
      .catch((error) => {
        if (error instanceof Error && error.name === "AbortError") return;
        setListState("error");
      });
    return () => controller.abort();
  }, []);

  function toggleExpand(personaId: string) {
    const next = expandedId === personaId ? null : personaId;
    setExpandedId(next);
    if (next && !profiles[next] && profileState[next] !== "loading") {
      setProfileState((state) => ({ ...state, [next]: "loading" }));
      void fetch(`/api/personas/${encodeURIComponent(next)}`, { cache: "no-store" })
        .then((response) => readJsonResponse<{ profile?: PersonaProfile }>(response, "Persona 读取失败"))
        .then((payload) => {
          if (!payload.profile) throw new Error("Persona 不存在");
          setProfiles((current) => ({ ...current, [next]: payload.profile as PersonaProfile }));
          setDrafts((current) => ({ ...current, [next]: personaDraftFromFiles((payload.profile as PersonaProfile).files) }));
          setIntroDrafts((current) => ({ ...current, [next]: payload.profile?.intro ?? "" }));
          setProfileState((state) => ({ ...state, [next]: "loaded" }));
        })
        .catch(() => setProfileState((state) => ({ ...state, [next]: "error" })));
    }
  }

  async function saveDraft(personaId: string) {
    const profile = profiles[personaId];
    const draft = drafts[personaId];
    if (!profile || !draft) return;
    const changedFiles = buildPersonaSavePayload(profile.files, draft).files;
    const intro = introDrafts[personaId] ?? profile.intro ?? "";
    const introChanged = intro.trim() !== (profile.intro ?? "");
    if (changedFiles.length === 0 && !introChanged) return;
    setSaveState((state) => ({ ...state, [personaId]: "busy" }));
    setSaveNotice((notice) => ({ ...notice, [personaId]: "正在保存…" }));
    try {
      const response = await fetch(`/api/personas/${encodeURIComponent(personaId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation: "updateProfile", ...(changedFiles.length ? { files: changedFiles } : {}), ...(introChanged ? { intro } : {}) }),
      });
      const body = await readJsonResponse<{ profile?: PersonaProfile; error?: string }>(response, "Persona 保存失败");
      if (!response.ok || !body.profile) throw new Error(body.error || "Persona 保存失败");
      setProfiles((current) => ({ ...current, [personaId]: body.profile as PersonaProfile }));
      setIntroDrafts((current) => ({ ...current, [personaId]: body.profile?.intro ?? "" }));
      setPersonas((current) => current?.map((persona) => persona.personaId === personaId
        ? { ...persona, intro: body.profile?.intro } : persona) ?? current);
      setSaveState((state) => ({ ...state, [personaId]: "done" }));
      setSaveNotice((notice) => ({ ...notice, [personaId]: "已保存，下一轮对话生效" }));
    } catch (error) {
      setSaveState((state) => ({ ...state, [personaId]: "error" }));
      setSaveNotice((notice) => ({ ...notice, [personaId]: error instanceof Error ? error.message : "Persona 保存失败" }));
    }
  }

  async function linkPersona(personaId: string) {
    if (!linkingAvatarId) return;
    setLinkState((state) => ({ ...state, [personaId]: "busy" }));
    setLinkNotice("");
    try {
      const response = await fetch(`/api/avatars/${encodeURIComponent(linkingAvatarId)}/persona`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPersonaSwitchPayload(personaId, linkingAvatarDisplayName)),
      });
      const body = await readJsonResponse<{ profile?: unknown; error?: string }>(response, "Persona 关联失败");
      if (!response.ok || !body.profile) throw new Error(body.error || "Persona 关联失败");
      router.push(`/avatars/${encodeURIComponent(linkingAvatarId)}`);
    } catch (error) {
      setLinkState((state) => ({ ...state, [personaId]: "error" }));
      setLinkNotice(error instanceof Error ? error.message : "Persona 关联失败");
    }
  }

  async function submitCreate() {
    const personaId = createId.trim();
    const personaName = createName.trim();
    if (!personaId) {
      setCreateState("error");
      setCreateNotice("请填写 Persona ID");
      return;
    }
    if (!personaName) {
      setCreateState("error");
      setCreateNotice("请填写 Persona 名称");
      return;
    }
    const missingRequired = CREATE_FIELDS.filter(
      ([filename, , , required]) => required && filename !== "IDENTITY.md" && !(createDraft[filename] ?? "").trim(),
    );
    if (missingRequired.length > 0) {
      setCreateState("error");
      setCreateNotice(`请填写：${missingRequired.map(([, label]) => label).join("、")}`);
      return;
    }
    const files: AvatarPersonaFile[] = [
      ...CREATE_FIELDS
        .filter(([filename]) => filename !== "IDENTITY.md" && (createDraft[filename] ?? "").trim())
        .map(([filename]) => ({ filename, content: (createDraft[filename] ?? "").trim() })),
      { filename: "IDENTITY.md", content: withIdentityHeading(personaName, createDraft["IDENTITY.md"] ?? "") },
    ];
    setCreateState("busy");
    setCreateNotice("正在创建…");
    try {
      const response = await fetch("/api/personas", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          personaId,
          files,
          ...(createIntro.trim() ? { intro: createIntro } : {}),
          ...(linkingAvatarId ? { avatarId: linkingAvatarId, avatarDisplayName: linkingAvatarDisplayName } : {}),
        }),
      });
      const body = await readJsonResponse<{ profile?: PersonaProfile; error?: string }>(response, "Persona 创建失败");
      if (!response.ok || !body.profile) throw new Error(body.error || "Persona 创建失败");
      if (linkingAvatarId) {
        router.push(`/avatars/${encodeURIComponent(linkingAvatarId)}`);
        return;
      }
      if (onCreated) {
        onCreated();
        return;
      }
      const created = body.profile;
      setPersonas((current) => [...(current ?? []), {
        personaId: created.personaId,
        personaName: created.personaName,
        intro: created.intro,
        linkedAvatarIds: created.linkedAvatarIds,
      }].sort((a, b) => a.personaId.localeCompare(b.personaId)));
      setCreating(false);
      setCreateName("");
      setCreateIntro("");
      setCreateId("");
      setCreateDraft({});
      setCreateState("idle");
      setCreateNotice("");
    } catch (error) {
      setCreateState("error");
      setCreateNotice(error instanceof Error ? error.message : "Persona 创建失败");
    }
  }

  return (
    <section className={styles.screen} data-embedded={embedded}>
      <header className={styles.intro}>
        <span>PERSONA LIBRARY</span>
        <h2>人设</h2>
        <p>选择已有的人设，或创建新的性格与对话风格，供多个角色使用。</p>
      </header>

      {linkingAvatarId ? (
        <div className={styles.linkingBanner} role="status">
          <Link2 />
          <span>正在为 <strong>{linkingAvatarDisplayName || linkingAvatarId}</strong> 选择人设</span>
          {linkNotice ? <small role="alert">{linkNotice}</small> : null}
        </div>
      ) : null}

      {listState === "loading" ? <p className={styles.notice}>正在加载 Persona 列表…</p> : null}
      {listState === "error" ? <p className={styles.notice} role="alert">Persona 列表读取失败</p> : null}

      <div className={styles.grid}>
          {(personas ?? []).map((persona) => {
            const expanded = expandedId === persona.personaId;
            const profile = profiles[persona.personaId];
            const draft = drafts[persona.personaId] ?? {};
            return (
              <article key={persona.personaId} className={`${styles.card} liquid-glass-surface`} data-expanded={expanded}>
                <button
                  type="button"
                  className={styles.cardHeader}
                  aria-expanded={expanded}
                  onClick={() => toggleExpand(persona.personaId)}
                >
                  <span className={styles.cardTitle}>
                    <strong>{persona.personaName}</strong>
                    <span className={styles.cardIntro}>{persona.intro || "为这个 Persona 添加一段简介"}</span>
                    <small>关联 {persona.linkedAvatarIds.length} 个数字人</small>
                  </span>
                  <ChevronDown className={styles.cardChevron} />
                </button>

                {linkingAvatarId ? (
                  <button
                    type="button"
                    className={`${styles.linkButton} liquid-glass-button`}
                    data-variant="primary"
                    disabled={linkState[persona.personaId] === "busy"}
                    onClick={() => void linkPersona(persona.personaId)}
                  >
                    <Link2 />{linkState[persona.personaId] === "busy" ? "关联中…" : `关联到 ${linkingAvatarDisplayName || linkingAvatarId}`}
                  </button>
                ) : null}

                {expanded ? (
                  <div className={styles.cardBody}>
                    {profileState[persona.personaId] === "loading" || !profile ? (
                      <p className={styles.notice}>正在加载 Persona 内容…</p>
                    ) : (
                      <>
                        <label className={styles.editorField}>
                          <span>卡片简介</span>
                          <textarea
                            value={introDrafts[persona.personaId] ?? profile.intro ?? ""}
                            maxLength={160}
                            aria-label={`${persona.personaName}的卡片简介`}
                            placeholder="用一两句话描述这个 Persona 的性格或定位"
                            onChange={(event) => setIntroDrafts((current) => ({ ...current, [persona.personaId]: event.target.value }))}
                          />
                        </label>
                        {profile.files.filter((file) => file.filename !== "AGENTS.md").map((file) => (
                          <label key={file.filename} className={styles.editorField}>
                            <span><FileText />{file.filename}</span>
                            <textarea
                              value={draft[file.filename] ?? file.content}
                              aria-label={`${file.filename} 内容`}
                              onChange={(event) => setDrafts((current) => ({
                                ...current,
                                [persona.personaId]: { ...current[persona.personaId], [file.filename]: event.target.value },
                              }))}
                            />
                          </label>
                        ))}
                        {profile.files.some((file) => file.filename === "AGENTS.md") ? (
                          <details className={styles.advanced}>
                            <summary>高级规则</summary>
                            {profile.files.filter((file) => file.filename === "AGENTS.md").map((file) => (
                              <label key={file.filename} className={styles.editorField}>
                                <span><FileText />{file.filename}</span>
                                <textarea
                                  value={draft[file.filename] ?? file.content}
                                  aria-label={`${file.filename} 内容`}
                                  onChange={(event) => setDrafts((current) => ({
                                    ...current,
                                    [persona.personaId]: { ...current[persona.personaId], [file.filename]: event.target.value },
                                  }))}
                                />
                              </label>
                            ))}
                          </details>
                        ) : null}
                        <div className={styles.saveRow}>
                          <button
                            type="button"
                            className={`${styles.saveButton} liquid-glass-button`}
                            data-variant="primary"
                            disabled={saveState[persona.personaId] === "busy" || (!isPersonaDraftDirty(profile.files, draft) && (introDrafts[persona.personaId] ?? profile.intro ?? "").trim() === (profile.intro ?? ""))}
                            onClick={() => void saveDraft(persona.personaId)}
                          >
                            {saveState[persona.personaId] === "busy" ? "保存中…" : "保存修改"}
                          </button>
                          {saveNotice[persona.personaId] ? <p role="status">{saveNotice[persona.personaId]}</p> : null}
                        </div>
                        {profile.linkedAvatarIds.length > 0 ? (
                          <p className={styles.linkedAvatars}>已关联：{profile.linkedAvatarIds.join("、")}</p>
                        ) : (
                          <p className={styles.linkedAvatars}>暂未关联任何数字人</p>
                        )}
                      </>
                    )}
                  </div>
                ) : null}
              </article>
            );
          })}

          <article className={`${styles.card} liquid-glass-surface`} data-expanded={creating} data-create="true">
            <button
              type="button"
              className={styles.cardHeader}
              aria-expanded={creating}
              onClick={() => setCreating((value) => !value)}
            >
              <span className={styles.cardIcon}><Plus /></span>
              <span className={styles.cardTitle}>
                <strong>创建人设</strong>
                <small>从头定义一个新的人格配置文件</small>
              </span>
              <ChevronDown className={styles.cardChevron} />
            </button>
            {creating ? (
              <div className={styles.cardBody}>
                <label className={styles.editorField}>
                  <span>人设名称</span>
                  <input
                    value={createName}
                    aria-label="人设名称"
                    placeholder="例如 温柔知性的伙伴"
                    onChange={(event) => setCreateName(event.target.value)}
                  />
                </label>
                <label className={styles.editorField}>
                  <span>Persona ID</span>
                  <input
                    value={createId}
                    aria-label="Persona ID"
                    placeholder="例如 sweet-sunshine"
                    onChange={(event) => setCreateId(event.target.value)}
                  />
                </label>
                <label className={styles.editorField}>
                  <span>卡片简介</span>
                  <textarea value={createIntro} maxLength={160} aria-label="新人设的卡片简介" placeholder="用一两句话描述性格或定位" onChange={(event) => setCreateIntro(event.target.value)} />
                </label>
                {CREATE_FIELDS.filter(([, , , required]) => required).map(([filename, label, description]) => (
                  <label key={filename} className={styles.editorField}>
                    <span><FileText />{label}.md{filename === "IDENTITY.md" ? "（可选）" : ""}</span>
                    <textarea
                      value={createDraft[filename] ?? ""}
                      aria-label={`${label} 内容`}
                      placeholder={description}
                      onChange={(event) => setCreateDraft((current) => ({ ...current, [filename]: event.target.value }))}
                    />
                  </label>
                ))}
                <details className={styles.advanced}>
                  <summary>高级规则</summary>
                  {CREATE_FIELDS.filter(([, , , required]) => !required).map(([filename, label, description]) => (
                    <label key={filename} className={styles.editorField}>
                      <span><FileText />{label}.md</span>
                      <textarea
                        value={createDraft[filename] ?? ""}
                        aria-label={`${label} 内容`}
                        placeholder={description}
                        onChange={(event) => setCreateDraft((current) => ({ ...current, [filename]: event.target.value }))}
                      />
                    </label>
                  ))}
                </details>
                <div className={styles.saveRow}>
                  <button
                    type="button"
                    className={`${styles.saveButton} liquid-glass-button`}
                    data-variant="primary"
                    disabled={createState === "busy"}
                    onClick={() => void submitCreate()}
                  >
                    {createState === "busy" ? "创建中…" : linkingAvatarId ? "创建并关联" : "创建"}
                  </button>
                  {createNotice ? <p role="status">{createNotice}</p> : null}
                </div>
              </div>
            ) : null}
          </article>
      </div>
    </section>
  );
}
