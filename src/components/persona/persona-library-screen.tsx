"use client";
import { useLanguage } from "@/components/language/language-provider";


import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ChevronDown, FileText, Link2, Pencil, Plus, Trash2, X } from "lucide-react";
import { isBuiltinPersonaId, type AvatarPersonaFile, type PersonaProfile, type PersonaSummary } from "@/lib/avatar-persona";
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
  ["IDENTITY.md", "IDENTITY", "身份背景与自我定位；用 {{role_name}} 表示人物姓名", true],
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
  const { t } = useLanguage();
  const router = useRouter();
  const [personas, setPersonas] = useState<PersonaSummary[] | null>(null);
  const [listState, setListState] = useState<LoadState>("loading");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [profiles, setProfiles] = useState<Record<string, PersonaProfile>>({});
  const [profileState, setProfileState] = useState<Record<string, LoadState>>({});
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({});
  const [nameDrafts, setNameDrafts] = useState<Record<string, string>>({});
  const [introDrafts, setIntroDrafts] = useState<Record<string, string>>({});
  const [saveState, setSaveState] = useState<Record<string, ActionState>>({});
  const [saveNotice, setSaveNotice] = useState<Record<string, string>>({});
  const [linkState, setLinkState] = useState<Record<string, ActionState>>({});
  const [linkNotice, setLinkNotice] = useState("");
  const [creating, setCreating] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createIntro, setCreateIntro] = useState("");
  const [createDraft, setCreateDraft] = useState<Record<string, string>>({});
  const [createState, setCreateState] = useState<ActionState>("idle");
  const [createNotice, setCreateNotice] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteState, setDeleteState] = useState<ActionState>("idle");
  const [actionNotice, setActionNotice] = useState<Record<string, string>>({});

  useEffect(() => {
    const controller = new AbortController();
    setListState("loading");
    void fetch("/api/personas", { cache: "no-store", signal: controller.signal })
      .then((response) => readJsonResponse<{ personas?: PersonaSummary[] }>(response, "人设列表读取失败"))
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
        .then((response) => readJsonResponse<{ profile?: PersonaProfile }>(response, "人设读取失败"))
        .then((payload) => {
          if (!payload.profile) throw new Error("人设不存在");
          setProfiles((current) => ({ ...current, [next]: payload.profile as PersonaProfile }));
          setDrafts((current) => ({ ...current, [next]: personaDraftFromFiles((payload.profile as PersonaProfile).files) }));
          setNameDrafts((current) => ({ ...current, [next]: payload.profile?.personaName ?? "" }));
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
    const personaName = (nameDrafts[personaId] ?? profile.personaName).trim();
    if (!personaName || personaName.length > 80 || /[\r\n]/.test(personaName)) {
      setSaveNotice((notice) => ({ ...notice, [personaId]: "请填写不超过 80 字的人设名称" }));
      return;
    }
    const nextDraft = { ...draft, "IDENTITY.md": withIdentityHeading(personaName, draft["IDENTITY.md"] ?? "") };
    const changedFiles = buildPersonaSavePayload(profile.files, nextDraft).files;
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
      const body = await readJsonResponse<{ profile?: PersonaProfile; error?: string }>(response, "人设保存失败");
      if (!response.ok || !body.profile) throw new Error(body.error || "人设保存失败");
      setProfiles((current) => ({ ...current, [personaId]: body.profile as PersonaProfile }));
      setDrafts((current) => ({ ...current, [personaId]: personaDraftFromFiles((body.profile as PersonaProfile).files) }));
      setNameDrafts((current) => ({ ...current, [personaId]: body.profile?.personaName ?? "" }));
      setIntroDrafts((current) => ({ ...current, [personaId]: body.profile?.intro ?? "" }));
      setPersonas((current) => current?.map((persona) => persona.personaId === personaId
        ? { ...persona, personaName: body.profile?.personaName ?? persona.personaName, intro: body.profile?.intro } : persona) ?? current);
      setSaveState((state) => ({ ...state, [personaId]: "done" }));
      setSaveNotice((notice) => ({ ...notice, [personaId]: "已保存，下一轮对话生效" }));
    } catch (error) {
      setSaveState((state) => ({ ...state, [personaId]: "error" }));
      setSaveNotice((notice) => ({ ...notice, [personaId]: error instanceof Error ? error.message : "人设保存失败" }));
    }
  }

  function hasUnsavedDraft(personaId: string) {
    const profile = profiles[personaId];
    const draft = drafts[personaId] ?? {};
    const personaName = (nameDrafts[personaId] ?? profile?.personaName ?? "").trim();
    const normalizedDraft = { ...draft, "IDENTITY.md": withIdentityHeading(personaName, draft["IDENTITY.md"] ?? "") };
    return Boolean(profile && (isPersonaDraftDirty(profile.files, normalizedDraft)
      || (nameDrafts[personaId] ?? profile.personaName).trim() !== profile.personaName
      || (introDrafts[personaId] ?? profile.intro ?? "").trim() !== (profile.intro ?? "")));
  }

  async function submitDelete(personaId: string) {
    setDeleteState("busy");
    try {
      const response = await fetch(`/api/personas/${encodeURIComponent(personaId)}`, { method: "DELETE" });
      const body = await readJsonResponse<{ archived?: boolean; error?: string }>(response, "人设删除失败");
      if (!response.ok || !body.archived) throw new Error(body.error || "人设删除失败");
      setPersonas((current) => current?.filter((persona) => persona.personaId !== personaId) ?? current);
      setExpandedId((current) => current === personaId ? null : current);
      setDeletingId(null);
      setDeleteState("done");
    } catch (error) {
      setDeleteState("error");
      setActionNotice((current) => ({ ...current, [personaId]: error instanceof Error ? error.message : "人设删除失败" }));
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
      const body = await readJsonResponse<{ profile?: unknown; error?: string }>(response, "人设关联失败");
      if (!response.ok || !body.profile) throw new Error(body.error || "人设关联失败");
      router.push(`/avatars/${encodeURIComponent(linkingAvatarId)}`);
    } catch (error) {
      setLinkState((state) => ({ ...state, [personaId]: "error" }));
      setLinkNotice(error instanceof Error ? error.message : "人设关联失败");
    }
  }

  async function submitCreate() {
    const personaName = createName.trim();
    if (!personaName) {
      setCreateState("error");
      setCreateNotice("请填写人设名称");
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
          files,
          ...(createIntro.trim() ? { intro: createIntro } : {}),
          ...(linkingAvatarId ? { avatarId: linkingAvatarId, avatarDisplayName: linkingAvatarDisplayName } : {}),
        }),
      });
      const body = await readJsonResponse<{ profile?: PersonaProfile; error?: string }>(response, "人设创建失败");
      if (!response.ok || !body.profile) throw new Error(body.error || "人设创建失败");
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
      setCreateDraft({});
      setCreateState("idle");
      setCreateNotice("");
    } catch (error) {
      setCreateState("error");
      setCreateNotice(error instanceof Error ? error.message : "人设创建失败");
    }
  }

  return (
    <section className={styles.screen} data-embedded={embedded}>
      <header className={styles.intro}>
        <div><h2>{t("人设")}</h2><p>{t("按用途与性格定义可复用的人设；人物姓名使用角色设置中的名称。")}</p></div>
        <button type="button" className={styles.createButton} aria-expanded={creating} onClick={() => setCreating((value) => !value)}><Plus />{t("创建人设")}</button>
      </header>

      {linkingAvatarId ? (
        <div className={styles.linkingBanner} role="status">
          <Link2 />
          <span>{t("正在为 ")}<strong>{linkingAvatarDisplayName || linkingAvatarId}</strong> {t(" 选择人设")}</span>
          {linkNotice ? <small role="alert">{linkNotice}</small> : null}
        </div>
      ) : null}

      {listState === "loading" ? <p className={styles.notice}>{t("正在加载人设列表…")}</p> : null}
      {listState === "error" ? <p className={styles.notice} role="alert">{t("人设列表读取失败")}</p> : null}

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
                    <span className={styles.cardIntro}>{persona.intro || t("为这个人设添加一段简介")}</span>
                    <small>{t("关联 ")}{persona.linkedAvatarIds.length}{t(" 个数字人")}</small>
                  </span>
                  <ChevronDown className={styles.cardChevron} />
                </button>

                <div className={styles.cardActions}>
                  <button type="button" className={styles.iconAction} aria-label={t("编辑人设") + (persona.personaName) + ""} title={t("编辑人设")} onClick={() => toggleExpand(persona.personaId)}><Pencil /></button>
                  <button type="button" className={styles.deleteAction} disabled={isBuiltinPersonaId(persona.personaId) || persona.linkedAvatarIds.length > 0} title={isBuiltinPersonaId(persona.personaId) ? t("内置人设不可删除") : persona.linkedAvatarIds.length ? t("请先解除数字人关联") : t("删除人设")} onClick={() => { if (hasUnsavedDraft(persona.personaId)) { setActionNotice((current) => ({ ...current, [persona.personaId]: "请先保存当前编辑内容，再删除。" })); return; } setDeletingId(persona.personaId); setDeleteState("idle"); }}><Trash2 />{t("删除")}</button>
                </div>

                {deletingId === persona.personaId ? <div className={styles.inlineAction} role="group" aria-label={t("确认删除") + (persona.personaName) + ""}><p>{t("确定删除“")}{persona.personaName}{t("”？删除后将移入可恢复的归档目录。")}</p><div><button type="button" className={styles.deleteAction} disabled={deleteState === "busy"} onClick={() => void submitDelete(persona.personaId)}>{deleteState === "busy" ? t("删除中…") : t("确认删除")}</button><button type="button" onClick={() => setDeletingId(null)}>{t("取消")}</button></div></div> : null}
                {actionNotice[persona.personaId] ? <p className={styles.actionNotice} role="status">{actionNotice[persona.personaId]}</p> : null}

                {linkingAvatarId ? (
                  <button
                    type="button"
                    className={`${styles.linkButton} liquid-glass-button`}
                    data-variant="primary"
                    disabled={linkState[persona.personaId] === "busy"}
                    onClick={() => void linkPersona(persona.personaId)}
                  >
                    <Link2 />{linkState[persona.personaId] === "busy" ? t("关联中…") : t("关联到 ") + (linkingAvatarDisplayName || linkingAvatarId) + ""}
                  </button>
                ) : null}

                {expanded ? (
                  <div className={styles.cardBody}>
                    {profileState[persona.personaId] === "loading" || !profile ? (
                      <p className={styles.notice}>{t("正在加载人设内容…")}</p>
                    ) : (
                      <>
                        <label className={styles.editorField}>
                          <span>{t("人设名称")}</span>
                          <input value={nameDrafts[persona.personaId] ?? profile.personaName} maxLength={80} aria-label={"" + (persona.personaName) + t("的人设名称")} onChange={(event) => setNameDrafts((current) => ({ ...current, [persona.personaId]: event.target.value }))} />
                        </label>
                        <label className={styles.editorField}>
                          <span>{t("卡片简介")}</span>
                          <textarea
                            value={introDrafts[persona.personaId] ?? profile.intro ?? ""}
                            maxLength={160}
                            aria-label={"" + (persona.personaName) + t("的卡片简介")}
                            placeholder={t("用一两句话描述这个人设的性格或定位")}
                            onChange={(event) => setIntroDrafts((current) => ({ ...current, [persona.personaId]: event.target.value }))}
                          />
                        </label>
                        {profile.files.filter((file) => file.filename !== "AGENTS.md").map((file) => (
                          <label key={file.filename} className={styles.editorField}>
                            <span><FileText />{file.filename}</span>
                            <textarea
                              value={draft[file.filename] ?? file.content}
                              aria-label={"" + (file.filename) + t(" 内容")}
                              onChange={(event) => setDrafts((current) => ({
                                ...current,
                                [persona.personaId]: { ...current[persona.personaId], [file.filename]: event.target.value },
                              }))}
                            />
                          </label>
                        ))}
                        {profile.files.some((file) => file.filename === "AGENTS.md") ? (
                          <details className={styles.advanced}>
                            <summary>{t("高级规则")}</summary>
                            {profile.files.filter((file) => file.filename === "AGENTS.md").map((file) => (
                              <label key={file.filename} className={styles.editorField}>
                                <span><FileText />{file.filename}</span>
                                <textarea
                                  value={draft[file.filename] ?? file.content}
                                  aria-label={"" + (file.filename) + t(" 内容")}
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
                            disabled={saveState[persona.personaId] === "busy" || !hasUnsavedDraft(persona.personaId)}
                            onClick={() => void saveDraft(persona.personaId)}
                          >
                            {saveState[persona.personaId] === "busy" ? t("保存中…") : t("保存修改")}
                          </button>
                          {saveNotice[persona.personaId] ? <p role="status">{saveNotice[persona.personaId]}</p> : null}
                        </div>
                        {profile.linkedAvatarIds.length > 0 ? (
                          <p className={styles.linkedAvatars}>{t("已关联：")}{profile.linkedAvatarIds.join("、")}</p>
                        ) : (
                          <p className={styles.linkedAvatars}>{t("暂未关联任何数字人")}</p>
                        )}
                      </>
                    )}
                  </div>
                ) : null}
              </article>
            );
          })}

          {creating ? <article className={`${styles.card} liquid-glass-surface`} data-expanded="true" data-create="true">
            <div className={styles.createPanelHeader}><span><strong>{t("新人设配置")}</strong><small>{t("从头定义一个新的人格配置文件")}</small></span><button type="button" aria-label={t("关闭创建人设")} title={t("关闭")} onClick={() => setCreating(false)}><X /></button></div>
              <div className={styles.cardBody}>
                <label className={styles.editorField}>
                  <span>{t("人设名称")}</span>
                  <input
                    value={createName}
                    maxLength={80}
                    aria-label={t("人设名称")}
                    placeholder={t("例如 阅读顾问 · 知性温柔")}
                    onChange={(event) => setCreateName(event.target.value)}
                  />
                </label>
                <label className={styles.editorField}>
                  <span>{t("卡片简介")}</span>
                  <textarea value={createIntro} maxLength={160} aria-label={t("新人设的卡片简介")} placeholder={t("用一两句话描述性格或定位")} onChange={(event) => setCreateIntro(event.target.value)} />
                </label>
                {CREATE_FIELDS.filter(([, , , required]) => required).map(([filename, label, description]) => (
                  <label key={filename} className={styles.editorField}>
                    <span><FileText />{t(label)}.md{filename === "IDENTITY.md" ? t("（可选）") : ""}</span>
                    <textarea
                      value={createDraft[filename] ?? ""}
                      aria-label={"" + (label) + t(" 内容")}
                      placeholder={description}
                      onChange={(event) => setCreateDraft((current) => ({ ...current, [filename]: event.target.value }))}
                    />
                  </label>
                ))}
                <details className={styles.advanced}>
                  <summary>{t("高级规则")}</summary>
                  {CREATE_FIELDS.filter(([, , , required]) => !required).map(([filename, label, description]) => (
                    <label key={filename} className={styles.editorField}>
                      <span><FileText />{t(label)}.md</span>
                      <textarea
                        value={createDraft[filename] ?? ""}
                        aria-label={"" + (label) + t(" 内容")}
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
                    {createState === "busy" ? t("创建中…") : linkingAvatarId ? t("创建并关联") : t("创建")}
                  </button>
                  {createNotice ? <p role="status">{createNotice}</p> : null}
                </div>
              </div>
          </article> : null}
      </div>
    </section>
  );
}
