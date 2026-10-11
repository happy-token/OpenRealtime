"use client";
import { LocalizedText } from "@/components/language/language-provider";

import { useLanguage } from "@/components/language/language-provider";


import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Check, ImagePlus, LoaderCircle, Maximize2, Minimize2, Sparkles, Upload, WandSparkles, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { normalizeAvatarSourceImage } from "@/lib/avatar-image-normalization";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import { readJsonResponse } from "@/lib/http-json-response";
import { ROLE_MODE_LABELS, type RolePresentationMode } from "@/lib/role-records";
import { completeRoleCreationResource, ROLE_CREATE_DRAFT_KEY } from "./role-creation-workbench-context";
import styles from "./role-avatar-composer.module.css";

type SourceMode = "upload" | "generate";
type QualitySignal = { label: string; detail: string; tone: "good" | "warn" };

const MAX_IMAGE_BYTES = 4_500_000;

export function RoleAvatarComposer({ presentation }: { presentation: "window" | "page" }) {
  const { t } = useLanguage();
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [sourceMode, setSourceMode] = useState<SourceMode>("upload");
  const [name, setName] = useState("");
  const [modes, setModes] = useState<RolePresentationMode[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState<"" | "generate" | "create">("");
  const [error, setError] = useState("");
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    try {
      const draft = JSON.parse(window.sessionStorage.getItem(ROLE_CREATE_DRAFT_KEY) ?? "{}") as { name?: string; modes?: RolePresentationMode[] };
      setName(draft.name?.trim() ? `${draft.name.trim()}形象` : "");
      setModes(Array.isArray(draft.modes) ? draft.modes : []);
    } catch { /* An empty composer remains usable. */ }
  }, []);

  useEffect(() => {
    if (presentation !== "window") return;
    const previousOverflow = document.body.style.overflow;
    const background = [document.querySelector<HTMLElement>("main"), document.querySelector<HTMLElement>("#workspace-navigation")]
      .filter((element): element is HTMLElement => Boolean(element));
    const previousAccessibility = background.map((element) => ({
      element,
      inert: element.inert,
      ariaHidden: element.getAttribute("aria-hidden"),
    }));
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || busy) return;
      router.back();
    };
    document.body.style.overflow = "hidden";
    background.forEach((element) => { element.inert = true; element.setAttribute("aria-hidden", "true"); });
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      previousAccessibility.forEach(({ element, inert, ariaHidden }) => {
        element.inert = inert;
        if (ariaHidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", ariaHidden);
      });
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [busy, presentation, router]);

  useEffect(() => () => {
    if (previewUrl.startsWith("blob:")) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const qualitySignals = useMemo(() => inspectAvatarImage(dimensions.width, dimensions.height, file?.size ?? 0), [dimensions, file?.size]);
  const nextSteps = describeNextSteps(modes);

  function close() {
    if (presentation === "window") router.back();
    else router.replace("/roles/new");
  }

  async function selectImageFile(nextFile: File) {
    setError("");
    if (!(["image/jpeg", "image/png", "image/webp"] as string[]).includes(nextFile.type)) {
      setError("请选择 JPEG、PNG 或 WebP 图片");
      return;
    }
    if (!nextFile.size || nextFile.size > MAX_IMAGE_BYTES) {
      setError("图片不能超过 4.5MB");
      return;
    }
    const url = URL.createObjectURL(nextFile);
    try {
      const size = await readImageDimensions(url);
      setFile(nextFile);
      setDimensions(size);
      setPreviewUrl(url);
      if (!name.trim()) setName(nextFile.name.replace(/\.[^.]+$/, "").slice(0, 46) || "新角色形象");
    } catch {
      URL.revokeObjectURL(url);
      setError("无法读取这张图片，请更换文件");
    }
  }

  async function generateImage() {
    if (!prompt.trim() || busy) return;
    setBusy("generate");
    setError("");
    try {
      const response = await fetch("/api/happyimage/avatar-images", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt.trim() }),
      });
      const payload = await readJsonResponse<{ imageUrl?: string; error?: string }>(response, "形象图片生成失败");
      if (!response.ok || !payload.imageUrl) throw new Error(payload.error || "形象图片生成失败");
      const normalized = await normalizeAvatarSourceImage(payload.imageUrl);
      const blob = await (await fetch(normalized)).blob();
      await selectImageFile(new File([blob], "generated-avatar.webp", { type: "image/webp" }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "形象图片生成失败");
    } finally {
      setBusy("");
    }
  }

  async function createAvatar() {
    if (!file || !name.trim() || busy) return;
    setBusy("create");
    setError("");
    try {
      const body = new FormData();
      body.set("name", name.trim());
      body.set("image", file);
      const response = await fetch("/api/user/avatars", { method: "POST", body });
      const payload = await readJsonResponse<{ avatar?: OwnedAvatarRecord; error?: string }>(response, "形象创建失败");
      if (!response.ok || !payload.avatar) throw new Error(payload.error || "形象创建失败");
      completeRoleCreationResource({ kind: "avatar", id: payload.avatar.avatar_id });
      close();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "形象创建失败");
      setBusy("");
    }
  }

  const content = <section
    className={styles.window}
    data-presentation={presentation}
    data-maximized={maximized}
    role={presentation === "window" ? "dialog" : undefined}
    aria-modal={presentation === "window" ? "true" : undefined}
    aria-labelledby="role-avatar-composer-title"
  >
    <header className={styles.titlebar}>
      <button type="button" onClick={close} aria-label={t("返回创建任务")}><ArrowLeft /></button>
      <div><strong id="role-avatar-composer-title">{t("新建数字人形象")}</strong></div>
      <span>{t("形象任务")}</span>
      {presentation === "window" ? <button type="button" onClick={() => setMaximized((value) => !value)} aria-label={maximized ? t("还原窗口") : t("最大化窗口")}>{maximized ? <Minimize2 /> : <Maximize2 />}</button> : null}
      <button type="button" onClick={close} disabled={Boolean(busy)} aria-label={t("关闭制作窗口")}><X /></button>
    </header>

    <div className={styles.body}>
      <section className={styles.stage} aria-label={t("数字人形象预览")}>
        {previewUrl ? <>
          <Image className={styles.stageBackdrop} src={previewUrl} alt="" fill sizes="70vw" unoptimized aria-hidden="true" />
          <Image className={styles.stageImage} src={previewUrl} alt={"" + (name || "新形象") + t("预览")} fill sizes="70vw" unoptimized priority />
        </> : <button className={styles.emptyStage} type="button" onClick={() => fileInputRef.current?.click()}>
          <span><ImagePlus /></span><strong>{t("添加一张角色形象")}</strong><small>{t("建议使用光线均匀、人物正面、背景简洁的图片")}</small><em><Upload />{t("选择图片")}</em>
        </button>}
        <div className={styles.stageShade} />
        <div className={styles.stageCaption}><span>{modes.length ? modes.map((mode) => ROLE_MODE_LABELS[mode]).join(" · ") : t("数字人模式")}</span><h1>{name.trim() || t("未命名形象")}</h1><p>{t("图片将保持原始比例完整展示，不会裁切或拉伸。")}</p></div>
      </section>

      <aside className={styles.config} aria-label={t("形象创建配置")}>
        <header><h2>{t("准备角色形象")}</h2><p>{t("创建后会自动回填到当前角色草稿，不会进入旧资产管理页面。")}</p></header>

        <section className={styles.module} data-open="true">
          <div className={styles.moduleHeading}><span>01</span><div><strong>{t("形象来源")}</strong><small>{file ? t("已准备图片") : t("选择上传或 AI 生成")}</small></div>{file ? <Check /> : null}</div>
          <div className={styles.sourceOptions}>
            <button type="button" data-selected={sourceMode === "upload"} onClick={() => setSourceMode("upload")}><Upload /><span><strong>{t("上传图片")}</strong><small>{t("JPEG、PNG、WebP，最大 4.5MB")}</small></span></button>
            <button type="button" data-selected={sourceMode === "generate"} onClick={() => setSourceMode("generate")}><WandSparkles /><span><strong>{t("AI 生成")}</strong><small>{t("描述人物外观与画面风格")}</small></span></button>
          </div>
          {sourceMode === "upload" ? <div className={styles.uploadRow}>
            <button type="button" onClick={() => fileInputRef.current?.click()}><ImagePlus />{file ? t("更换图片") : t("选择图片")}</button>
            <span>{file?.name ?? t("尚未选择文件")}</span>
          </div> : <div className={styles.promptBox}>
            <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={t("例如：短发女性产品顾问，正面半身，简洁灰色背景，自然光…")} />
            <button type="button" disabled={!prompt.trim() || Boolean(busy)} onClick={() => void generateImage()}>{busy === "generate" ? <LoaderCircle /> : <Sparkles />}{busy === "generate" ? t("正在生成…") : t("生成形象")}</button>
          </div>}
          <input ref={fileInputRef} hidden type="file" accept="image/jpeg,image/png,image/webp" onChange={(event: ChangeEvent<HTMLInputElement>) => { const selected = event.target.files?.[0]; if (selected) void selectImageFile(selected); event.target.value = ""; }} />
        </section>

        <section className={styles.module} data-ready={Boolean(file)}>
          <div className={styles.moduleHeading}><span>02</span><div><strong>{t("名称与质量检查")}</strong><small>{file ? `${dimensions.width} × ${dimensions.height}` : t("添加图片后自动检查")}</small></div>{file ? <Check /> : null}</div>
          <label className={styles.nameField}><span>{t("形象名称")}</span><input value={name} maxLength={50} onChange={(event) => setName(event.target.value)} placeholder={t("例如：产品顾问形象")} /></label>
          {file ? <div className={styles.qualityList}>{qualitySignals.map((signal) => <div key={signal.label} data-tone={signal.tone}><i>{signal.tone === "good" ? <Check /> : "!"}</i><span><strong>{<LocalizedText text={signal.label} />}</strong><small>{<LocalizedText text={signal.detail} />}</small></span></div>)}</div> : null}
        </section>

        <section className={styles.module} data-ready={Boolean(file && name.trim())}>
          <div className={styles.moduleHeading}><span>03</span><div><strong>{t("保存并继续")}</strong><small>{nextSteps}</small></div></div>
          <div className={styles.compatibility}><span>{t("后续任务")}</span><p>{nextSteps}</p></div>
          {error ? <p className={styles.error} role="alert">{t(error)}{error.includes("登录") ? <Link href="/api/user/login?next=%2Froles%2Fnew%2Favatar">{t("前往登录")}</Link> : null}</p> : null}
          <button className={styles.primary} type="button" disabled={!file || !name.trim() || Boolean(busy)} onClick={() => void createAvatar()}>{busy === "create" ? <LoaderCircle /> : <Check />}{busy === "create" ? t("正在创建形象…") : t("创建形象并返回任务")}</button>
        </section>
      </aside>
    </div>
  </section>;

  return presentation === "window"
    ? <div className={styles.backdrop} onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) close(); }}>{content}</div>
    : <main className={styles.page}>{content}</main>;
}

export function inspectAvatarImage(width: number, height: number, bytes: number): QualitySignal[] {
  if (!width || !height) return [];
  const shortestEdge = Math.min(width, height);
  const ratio = width / height;
  return [
    shortestEdge >= 720
      ? { label: "清晰度良好", detail: `短边 ${shortestEdge}px，适合后续数字人处理`, tone: "good" }
      : { label: "清晰度偏低", detail: `短边仅 ${shortestEdge}px，建议使用短边至少 720px 的图片`, tone: "warn" },
    ratio >= 0.56 && ratio <= 1.78
      ? { label: "画幅可用", detail: "当前比例可以完整适配横屏与竖屏预览", tone: "good" }
      : { label: "画幅较极端", detail: "建议裁剪到 9:16、3:4、1:1 或 16:9 附近", tone: "warn" },
    bytes <= 2_000_000
      ? { label: "文件大小合适", detail: `${formatBytes(bytes)}，上传与处理速度较好`, tone: "good" }
      : { label: "文件较大", detail: `${formatBytes(bytes)}，可以使用但处理时间可能更长`, tone: "warn" },
  ];
}

export function describeNextSteps(modes: readonly RolePresentationMode[]) {
  const steps = [modes.includes("realtime") ? "实时驱动" : "", modes.includes("offline") || modes.includes("lip-sync") ? "动作底片" : "", modes.includes("offline") ? "口型对齐" : ""].filter(Boolean);
  return steps.length ? `形象创建后继续配置：${steps.join("、")}` : "形象创建后返回角色任务清单";
}

function readImageDimensions(url: string) {
  return new Promise<{ width: number; height: number }>((resolve, reject) => {
    const image = new window.Image();
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
    image.onerror = reject;
    image.src = url;
  });
}

function formatBytes(bytes: number) {
  return bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)}MB` : `${Math.max(1, Math.round(bytes / 1000))}KB`;
}
