"use client";

import Image from "next/image";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Check, Film, ImagePlus, LoaderCircle, LockKeyhole, Maximize2, Play, Sparkles, Upload, X } from "lucide-react";
import { useEffect, useRef, useState, type SyntheticEvent } from "react";
import {
  ANAM_AVATAR_NAME_MAX_LENGTH,
  ANAM_AVATAR_NAME_MIN_LENGTH,
  ANAM_AVATAR_NAME_REQUIREMENT,
  isValidAnamAvatarName,
  suggestAnamAvatarName,
} from "@/lib/anam-avatar-name";
import type { AnamHostedAvatar } from "@/lib/anam-avatars";
import {
  acceptOwnedAvatarRealtimeBinding,
  createOwnedAvatar,
  fetchOwnedAvatar,
} from "@/lib/avatar-catalog-client";
import {
  isSegmentedAvatarAsset,
  loadCurrentAvatarCatalog,
  loadInternalPresetAvatars,
} from "@/lib/avatar-library-catalog-client";
import { normalizeAvatarSourceImage } from "@/lib/avatar-image-normalization";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import { readJsonResponse } from "@/lib/http-json-response";
import { isInternalAvatarPresetId } from "@/lib/internal-avatar-ids";
import { classifyMediaAspectRatio } from "@/lib/media-aspect-fit";
import { AvatarActionStudio } from "./avatar-action-studio";
import { StudioConfigOverlay } from "./studio-config-overlay";
import styles from "./avatar-studio.module.css";

type SourceMode = "library" | "upload" | "happyimage";
type CreationTask = "realtime" | "action";
type SourceChoice = { id: string; name: string; imageUrl: string };
type BusyState = "" | "image" | "save" | "anam" | "accept";

export function AvatarStudio({
  initialTask = "realtime",
  initialAvatarId = "",
}: {
  initialTask?: CreationTask;
  initialAvatarId?: string;
} = {}) {
  const [task, setTask] = useState<CreationTask>(initialTask);
  const [mode, setMode] = useState<SourceMode>("library");
  const [libraryChoices, setLibraryChoices] = useState<SourceChoice[]>([]);
  const [source, setSource] = useState<SourceChoice | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [displayNameOrigin, setDisplayNameOrigin] = useState<"" | "asset" | "user">("");
  const [defaultAvatarName, setDefaultAvatarName] = useState("数字人1");
  const [anamDisplayName, setAnamDisplayName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [createdAvatar, setCreatedAvatar] = useState<OwnedAvatarRecord | null>(null);
  const [anamCandidate, setAnamCandidate] = useState<AnamHostedAvatar | null>(null);
  const [busy, setBusy] = useState<BusyState>("");
  const [error, setError] = useState("");
  const [currentStep, setCurrentStep] = useState(initialAvatarId ? 2 : 0);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [mobileConfigOpen, setMobileConfigOpen] = useState(false);
  const [stagePreviewFit, setStagePreviewFit] = useState<"landscape" | "square" | "portrait">("square");

  function handleStagePortraitLoad(event: SyntheticEvent<HTMLImageElement>): void {
    const img = event.currentTarget;
    setStagePreviewFit(classifyMediaAspectRatio(img.naturalWidth, img.naturalHeight));
  }
  const [libraryDockPinned, setLibraryDockPinned] = useState(false);
  const [libraryDockHovered, setLibraryDockHovered] = useState(false);
  const [libraryDockFocused, setLibraryDockFocused] = useState(false);
  const [pageVisible, setPageVisible] = useState(true);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const internalAvatars = loadInternalPresetAvatars();
    setLibraryChoices(internalAvatars.map((avatar) => ({
      id: avatar.avatarId,
      name: avatar.displayName,
      imageUrl: avatar.source.imageUrl,
    })));
    const controller = new AbortController();
    void loadCurrentAvatarCatalog(controller.signal)
      .then((avatars) => {
        setLibraryChoices(avatars.filter((avatar) => isSegmentedAvatarAsset(avatar)).map((avatar) => ({
          id: avatar.avatarId,
          name: avatar.displayName,
          imageUrl: avatar.source.imageUrl,
        })));
        setDefaultAvatarName(suggestNextNumberedAvatarName(avatars
          .filter((avatar) => avatar.source.kind === "owned" && avatar.ownerId)
          .map((avatar) => avatar.displayName)));
      })
      .catch((loadError) => {
        if (loadError instanceof Error && loadError.name === "AbortError") return;
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!initialAvatarId) return;
    const controller = new AbortController();
    void fetchOwnedAvatar(initialAvatarId, controller.signal).then((avatar) => {
      if (!avatar) throw new Error("找不到这个 Avatar");
      setCreatedAvatar(avatar);
      setSource({ id: avatar.avatar_id, name: avatar.display_name, imageUrl: avatar.source_image_url });
      setDisplayName(avatar.display_name);
      setDisplayNameOrigin("asset");
      setAnamDisplayName(suggestAnamAvatarName(avatar.display_name));
    }).catch((loadError) => {
      if (loadError instanceof Error && loadError.name === "AbortError") return;
      setError(loadError instanceof Error ? loadError.message : "Avatar 读取失败");
    });
    return () => controller.abort();
  }, [initialAvatarId]);

  useEffect(() => {
    if (!previewOpen) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreviewOpen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [previewOpen]);

  function chooseSource(choice: SourceChoice) {
    if (createdAvatar) return;
    setSource(choice);
    if (mode === "library") {
      setDisplayName(choice.name);
      setDisplayNameOrigin("asset");
    } else if (displayNameOrigin !== "user") {
      setDisplayName("");
      setDisplayNameOrigin("");
    }
    setError("");
  }

  useEffect(() => {
    if (mode !== "library" || createdAvatar || libraryChoices.length === 0) return;
    if (source && libraryChoices.some((choice) => choice.id === source.id)) return;
    chooseSource(libraryChoices[0]);
  }, [mode, source, createdAvatar, libraryChoices]);

  useEffect(() => {
    const updateVisibility = () => setPageVisible(document.visibilityState === "visible");
    updateVisibility();
    document.addEventListener("visibilitychange", updateVisibility);
    return () => document.removeEventListener("visibilitychange", updateVisibility);
  }, []);

  useEffect(() => {
    if (mode !== "library" || createdAvatar || libraryChoices.length < 2 || !pageVisible) return;
    if (libraryDockPinned || libraryDockHovered || libraryDockFocused) return;
    const timer = window.setTimeout(() => {
      const currentIndex = source ? libraryChoices.findIndex((choice) => choice.id === source.id) : -1;
      chooseSource(libraryChoices[(currentIndex + 1) % libraryChoices.length]);
    }, 1_000);
    return () => window.clearTimeout(timer);
  }, [mode, source, createdAvatar, libraryChoices, pageVisible, libraryDockPinned, libraryDockHovered, libraryDockFocused]);

  function changeSourceMode(nextMode: SourceMode) {
    if (nextMode === mode || createdAvatar) return;
    setMode(nextMode);
    setSource(null);
    if (displayNameOrigin !== "user") {
      setDisplayName("");
      setDisplayNameOrigin("");
    }
    setError("");
  }

  async function importUpload(file: File | undefined) {
    if (!file) return;
    setError("");
    if (!file.type.startsWith("image/")) return setError("请选择图片文件");
    if (file.size > 8 * 1024 * 1024) return setError("图片不能超过 8MB");
    try {
      const imageUrl = await readFileAsDataUrl(file);
      chooseSource({ id: `upload-${crypto.randomUUID()}`, name: file.name, imageUrl });
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "图片读取失败");
    }
  }

  async function generateWithHappyImage() {
    if (!prompt.trim() || busy) return;
    setBusy("image");
    setError("");
    try {
      const response = await fetch("/api/happyimage/avatar-images", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt.trim() }),
      });
      const payload = await readJsonResponse<{ imageUrl?: string; error?: string }>(response, "HappyImage 生成失败");
      if (!response.ok || !payload.imageUrl) throw new Error(payload.error || "HappyImage 没有返回图片");
      chooseSource({ id: `happyimage-${crypto.randomUUID()}`, name: prompt.trim().slice(0, 24), imageUrl: payload.imageUrl });
      setMobileConfigOpen(false);
    } catch (generationError) {
      setError(generationError instanceof Error ? generationError.message : "HappyImage 生成失败");
    } finally {
      setBusy("");
    }
  }

  async function createAvatar(nextTask: CreationTask) {
    if (!source || busy || createdAvatar) return;
    const resolvedDisplayName = displayName.trim() || (mode === "library" ? "" : defaultAvatarName);
    if (!resolvedDisplayName) return;
    setTask(nextTask);
    setBusy("save");
    setError("");
    setDisplayName(resolvedDisplayName);
    try {
      if (mode === "library" && !isInternalAvatarPresetId(source.id)) {
        const avatar = await fetchOwnedAvatar(source.id);
        if (!avatar) throw new Error("找不到这个 Avatar");
        setCreatedAvatar(avatar);
        setAnamDisplayName(suggestAnamAvatarName(avatar.display_name));
        setCurrentStep(2);
        return;
      }
      const sourceImageUrl = await normalizeAvatarSourceImage(source.imageUrl);
      const avatar = await createOwnedAvatar({
        displayName: resolvedDisplayName,
        sourceImageDataUrl: sourceImageUrl,
        ...(isInternalAvatarPresetId(source.id) ? { avatarId: source.id } : {}),
      });
      setCreatedAvatar(avatar);
      setAnamDisplayName(suggestAnamAvatarName(avatar.display_name));
      setCurrentStep(2);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Avatar 保存失败");
    } finally {
      setBusy("");
    }
  }

  async function createRealtimeCandidate() {
    if (!createdAvatar || busy) return;
    if (!isValidAnamAvatarName(anamDisplayName)) {
      setError(ANAM_AVATAR_NAME_REQUIREMENT);
      return;
    }
    setBusy("anam");
    setError("");
    try {
      const form = new FormData();
      form.set("displayName", anamDisplayName.trim());
      form.set("image", await imageUrlToFile(createdAvatar.source_image_url, createdAvatar.display_name));
      const response = await fetch("/api/anam/avatars", { method: "POST", body: form });
      const payload = await readJsonResponse<{ avatar?: AnamHostedAvatar; error?: string }>(response, "实时形象创建失败");
      if (!response.ok || !payload.avatar) throw new Error(payload.error || "实时形象创建失败");
      setAnamCandidate(payload.avatar);
      setMobileConfigOpen(false);
    } catch (candidateError) {
      setError(candidateError instanceof Error ? candidateError.message : "实时形象创建失败");
    } finally {
      setBusy("");
    }
  }

  async function acceptRealtimeCandidate() {
    if (!createdAvatar || !anamCandidate || busy) return;
    setBusy("accept");
    try {
      const avatar = await acceptOwnedAvatarRealtimeBinding(createdAvatar.avatar_id, {
        provider_avatar_id: anamCandidate.id,
        avatar_model: anamCandidate.activeVersion,
        preview_video_url: anamCandidate.videoUrl,
      });
      setCreatedAvatar(avatar);
      setAnamCandidate(null);
      setCurrentStep(3);
      setMobileConfigOpen(false);
    } catch (acceptError) {
      setError(acceptError instanceof Error ? acceptError.message : "实时形象保存失败");
    } finally {
      setBusy("");
    }
  }

  function changeAvatar() {
    if (busy) return;
    setCreatedAvatar(null);
    setAnamCandidate(null);
    setCurrentStep(0);
    setError("");
  }

  function changeTask(nextTask: CreationTask) {
    if (nextTask === task) return;
    setTask(nextTask);
    setCurrentStep(createdAvatar ? 2 : 0);
    setError("");
  }

  const anamDisplayNameLength = anamDisplayName.trim().length;
  const validAnamDisplayName = isValidAnamAvatarName(anamDisplayName);
  const selectedAvatarImageUrl = createdAvatar
    ? libraryChoices.find((choice) => choice.id === createdAvatar.avatar_id)?.imageUrl ?? createdAvatar.source_image_url
    : "";
  const realtimePreviewVideoUrl = anamCandidate?.videoUrl || createdAvatar?.realtime_binding?.preview_video_url || "";
  const previewImageUrl = selectedAvatarImageUrl || source?.imageUrl || "";
  const previewDisplayName = createdAvatar?.display_name
    || displayName
    || (source && mode !== "library" ? defaultAvatarName : "未命名 Avatar");
  const avatarNameLocked = isAvatarNameLocked(mode);
  return (
    <section className={styles.studio} aria-label="创建数字人工作区">
      {currentStep < 3 ? <div className={styles.creationWorkspace} data-stage={currentStep === 0 ? "select" : "configure"}>
        {currentStep === 0 ? (
          <StudioConfigOverlay open={mobileConfigOpen} onOpenChange={setMobileConfigOpen} label="配置 Avatar" icon={<Sparkles aria-hidden="true" />}>
          <section key="source" className={styles.wizardPanel} aria-labelledby="avatar-source-step-title">
          <div className={styles.sectionHeading}>
            <h2 id="avatar-source-step-title">选择 Avatar 形象</h2>
            <p>选择或创建一个 Avatar 形象，确认后再选择下一步要创建的能力。</p>
          </div>

          <div className={styles.modeTabs} role="group" aria-label="形象来源">
            <button type="button" data-active={mode === "library"} onClick={() => changeSourceMode("library")}>
              <ImagePlus aria-hidden="true" /><span><strong>从资产库选择</strong><small>使用已有内部预置形象</small></span>
            </button>
            <button type="button" data-active={mode === "upload"} onClick={() => changeSourceMode("upload")}>
              <Upload aria-hidden="true" /><span><strong>上传图片</strong><small>选择本机正面人物照片</small></span>
            </button>
          </div>

          {mode === "upload" ? (
            <button className={styles.uploadDrop} type="button" onClick={() => fileInput.current?.click()}>
              <Upload aria-hidden="true" />
              <strong>选择一张清晰正面图片</strong>
              <span>JPEG、PNG、WebP，最大 8MB</span>
              <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => void importUpload(event.target.files?.[0])} />
            </button>
          ) : null}

          {mode === "happyimage" ? (
            <div className={styles.promptBox}>
              <Sparkles aria-hidden="true" />
              <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="描述人物外观、服装、光线与背景…" />
              <button type="button" onClick={() => void generateWithHappyImage()} disabled={!prompt.trim() || Boolean(busy)}>
                {busy === "image" ? <LoaderCircle className={styles.spin} /> : <ImagePlus />}
                生成形象
              </button>
              <small>直接使用当前 OpenRealtime 账户额度，不触发额外授权跳转。</small>
            </div>
          ) : null}

          {error ? <p className={styles.error} role="alert">{error}</p> : null}
          <footer className={styles.wizardNavigation} data-has-source={Boolean(source)}>
            {source ? (
              <label className={styles.nameField} data-locked={avatarNameLocked}>
                <span>数字人名称{avatarNameLocked ? <LockKeyhole aria-hidden="true" /> : null}</span>
                <input
                  value={displayName}
                  maxLength={ANAM_AVATAR_NAME_MAX_LENGTH}
                  readOnly={avatarNameLocked}
                  aria-readonly={avatarNameLocked}
                  onChange={(event) => {
                    if (avatarNameLocked) return;
                    setDisplayName(event.target.value);
                    setDisplayNameOrigin(event.target.value ? "user" : "");
                    setError("");
                  }}
                  placeholder={`不填写则使用${defaultAvatarName}`}
                />
                <small>{avatarNameLocked
                  ? "名称沿用资产库中的数字人名称，不能修改"
                  : `请填写数字人名称；留空将自动使用“${defaultAvatarName}”`}</small>
              </label>
            ) : <p className={styles.selectionPrompt}>选择一个 Avatar 后继续</p>}
            <div className={styles.nextTaskBlock}>
              <div className={styles.nextTaskHeading}>
                <strong>确认形象并选择下一步</strong>
                <small>两项能力后续都可以继续添加</small>
              </div>
              <div className={styles.nextTaskChoices} role="group" aria-label="选择下一步操作">
                <button
                  className={styles.nextTaskChoice}
                  type="button"
                  disabled={!source || (avatarNameLocked && !displayName.trim()) || Boolean(busy)}
                  onClick={() => void createAvatar("realtime")}
                >
                  <span className={styles.nextTaskIcon}>{busy === "save" && task === "realtime" ? <LoaderCircle className={styles.spin} /> : <Play />}</span>
                  <span><strong>创建实时驱动</strong></span>
                  <ArrowRight aria-hidden="true" />
                </button>
                <button
                  className={styles.nextTaskChoice}
                  type="button"
                  disabled={!source || (avatarNameLocked && !displayName.trim()) || Boolean(busy)}
                  onClick={() => void createAvatar("action")}
                >
                  <span className={styles.nextTaskIcon}>{busy === "save" && task === "action" ? <LoaderCircle className={styles.spin} /> : <Film />}</span>
                  <span><strong>创建 Avatar 动作</strong></span>
                  <ArrowRight aria-hidden="true" />
                </button>
              </div>
            </div>
          </footer>
          </section>
          </StudioConfigOverlay>
        ) : null}

        {currentStep === 0 ? (
          <section
            key={`visual-${mode}`}
            className={styles.visualStage}
            aria-label="Avatar 视觉工作区"
          >
            <div className={styles.visualStageBody}>
              {mode === "library" ? (
                <div className={styles.libraryDockStage}>
                  <div className={styles.libraryStagePreview}>
                    {source ? (
                      <button className={styles.stageImage} type="button" aria-label={`预览 ${previewDisplayName}`} onClick={() => setPreviewOpen(true)}>
                        <Image className={styles.stageBackdropImage} src={source.imageUrl} alt="" aria-hidden="true" fill sizes="(max-width: 900px) 100vw, 70vw" unoptimized />
                        <Image className={styles.stagePortraitImage} data-fit={stagePreviewFit} src={source.imageUrl} alt="" fill sizes="(max-width: 900px) 100vw, 70vw" unoptimized onLoad={handleStagePortraitLoad} />
                      </button>
                    ) : (
                      <div className={styles.emptyStage}><LoaderCircle className={styles.spin} aria-hidden="true" /><strong>正在加载 Avatar 形象…</strong></div>
                    )}
                    <div
                      className={styles.libraryDock}
                      role="group"
                      aria-label="内部预制形象"
                      data-auto-advance={libraryDockPinned || libraryDockHovered || libraryDockFocused ? "paused" : "running"}
                      onPointerEnter={() => setLibraryDockHovered(true)}
                      onPointerLeave={() => setLibraryDockHovered(false)}
                      onFocusCapture={() => setLibraryDockFocused(true)}
                      onBlurCapture={(event) => {
                        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setLibraryDockFocused(false);
                      }}
                    >
                      {libraryChoices.map((choice) => {
                        const isSelected = source?.id === choice.id;
                        return (
                          <button
                            key={choice.id}
                            className={styles.libraryDockCard}
                            type="button"
                            data-current={isSelected ? "true" : undefined}
                            aria-current={isSelected ? "true" : undefined}
                            aria-label={`选择 ${choice.name}`}
                            onClick={() => {
                              setLibraryDockPinned(true);
                              chooseSource(choice);
                            }}
                          >
                            <span className={styles.libraryDockMedia}>
                              <Image src={choice.imageUrl} alt="" fill sizes="88px" unoptimized />
                            </span>
                            <strong>{choice.name}</strong>
                          </button>
                        );
                      })}
                      <button className={styles.libraryDockUpload} type="button" aria-label="改为上传图片" onClick={() => changeSourceMode("upload")}>
                        <Upload aria-hidden="true" /><span>上传图片</span>
                      </button>
                    </div>
                  </div>
                </div>
              ) : source ? (
                <button className={styles.stageImage} type="button" aria-label={`预览 ${previewDisplayName}`} onClick={() => setPreviewOpen(true)}>
                  <Image className={styles.stageBackdropImage} src={source.imageUrl} alt="" aria-hidden="true" fill sizes="(max-width: 900px) 100vw, 70vw" unoptimized />
                  <Image className={styles.stagePortraitImage} data-fit={stagePreviewFit} src={source.imageUrl} alt="" fill sizes="(max-width: 900px) 100vw, 70vw" unoptimized onLoad={handleStagePortraitLoad} />
                </button>
              ) : (
                <div className={styles.emptyStage}>{mode === "upload" ? <Upload aria-hidden="true" /> : <Sparkles aria-hidden="true" />}<strong>{mode === "upload" ? "在左侧上传一张图片" : "在左侧描述并创建图片"}</strong><span>图片结果会在这里以大图展示</span></div>
              )}
            </div>
          </section>
        ) : null}

        {currentStep === 2 && createdAvatar ? (
          task === "realtime" ? <>
            <StudioConfigOverlay open={mobileConfigOpen} onOpenChange={setMobileConfigOpen} label="实时驱动配置" icon={<Play aria-hidden="true" />}>
            <aside className={styles.taskSidebar}>
              <section className={styles.selectedAvatar} aria-label="当前共享 Avatar">
                <button className={styles.selectedAvatarImage} type="button" aria-label={`预览 ${createdAvatar.display_name}`} onClick={() => setPreviewOpen(true)}><Image src={selectedAvatarImageUrl} alt="" fill sizes="56px" unoptimized /></button>
                <div><strong>{createdAvatar.display_name}</strong></div>
                <button type="button" aria-label="上一步：返回选择 Avatar 形象" onClick={changeAvatar}><ArrowLeft aria-hidden="true" />上一步</button>
              </section>
              <section className={styles.capabilityModule} aria-labelledby="realtime-creation-title" data-transition="in-page">
                <header><h2 id="realtime-creation-title" aria-label="创建实时驱动 Avatar">实时驱动配置</h2><p>完成后需确认效果，确认前不会绑定。</p></header>
                {createdAvatar.realtime_binding ? (
                  <p className={styles.accepted}><Check />实时驱动已确认并绑定</p>
                ) : anamCandidate ? (
                  <div className={styles.candidate}>
                    {!anamCandidate.videoUrl ? <p>实时形象正在处理。可稍后在 Anam 目录刷新预览。</p> : null}
                    <button type="button" onClick={() => void acceptRealtimeCandidate()} disabled={Boolean(busy)}><Play />确认效果并启用</button>
                  </div>
                ) : (
                  <div className={styles.realtimeCandidateSetup}>
                    <label>
                      <span>Anam 形象名称</span>
                      <input
                        value={anamDisplayName}
                        minLength={ANAM_AVATAR_NAME_MIN_LENGTH}
                        maxLength={ANAM_AVATAR_NAME_MAX_LENGTH}
                        aria-describedby="anam-create-name-requirement"
                        aria-invalid={Boolean(anamDisplayNameLength) && !validAnamDisplayName}
                        disabled={Boolean(busy)}
                        onChange={(event) => { setAnamDisplayName(event.target.value); setError(""); }}
                      />
                      <small id="anam-create-name-requirement" data-invalid={Boolean(anamDisplayNameLength) && !validAnamDisplayName}>
                        Anam 新建接口要求 3–50 个字符<em>{anamDisplayNameLength} / {ANAM_AVATAR_NAME_MAX_LENGTH}</em>
                      </small>
                    </label>
                    <button type="button" onClick={() => void createRealtimeCandidate()} disabled={Boolean(busy) || !validAnamDisplayName}>
                      {busy === "anam" ? <LoaderCircle className={styles.spin} /> : <Play />}创建实时驱动形象
                    </button>
                  </div>
                )}
                {error ? <p className={styles.error} role="alert">{error}</p> : null}
                <footer><button type="button" onClick={() => changeTask("action")}><Film />继续创建动作</button><Link href={`/avatars/${encodeURIComponent(createdAvatar.avatar_id)}`}>查看 Avatar</Link></footer>
              </section>
            </aside>
            </StudioConfigOverlay>
            <section className={styles.visualStage} aria-label="实时驱动效果预览">
              <header><strong>{realtimePreviewVideoUrl ? "效果确认" : "当前形象"}</strong></header>
              <div className={styles.visualStageBody}>
                {realtimePreviewVideoUrl
                  ? <video className={styles.stageVideo} src={realtimePreviewVideoUrl} controls autoPlay muted loop playsInline />
                  : <button className={styles.stageImage} type="button" aria-label={`预览 ${createdAvatar.display_name}`} onClick={() => setPreviewOpen(true)}><Image className={styles.stageBackdropImage} src={selectedAvatarImageUrl} alt="" aria-hidden="true" fill sizes="(max-width: 900px) 100vw, 70vw" unoptimized /><Image className={styles.stagePortraitImage} data-fit={stagePreviewFit} src={selectedAvatarImageUrl} alt="" fill sizes="(max-width: 900px) 100vw, 70vw" unoptimized onLoad={handleStagePortraitLoad} /><span><strong>{createdAvatar.display_name}</strong><em>创建后将在这里播放实时驱动效果</em></span><Maximize2 aria-hidden="true" /></button>}
              </div>
              <footer><span>{createdAvatar.realtime_binding ? "已确认并启用" : anamCandidate ? "等待效果确认，确认后启用" : "尚未创建实时驱动效果"}</span></footer>
            </section>
          </> : <AvatarActionStudio
            avatarId={createdAvatar.avatar_id}
            embedded
            previewImageUrl={selectedAvatarImageUrl}
            onChangeAvatar={changeAvatar}
            onPreviewAvatar={() => setPreviewOpen(true)}
            mobileConfigOpen={mobileConfigOpen}
            onMobileConfigOpenChange={setMobileConfigOpen}
          />
        ) : null}
      </div> : null}

      {currentStep === 3 && createdAvatar && task === "realtime" ? (
        <section key="done" className={styles.completionPanel} aria-labelledby="avatar-completion-title">
          <Check aria-hidden="true" />
          <h2 id="avatar-completion-title">实时驱动已启用</h2>
          <p>现在可以使用这个 Avatar 开始对话测试。</p>
          <div>
            <button type="button" onClick={() => setCurrentStep(2)}><ArrowLeft aria-hidden="true" />上一步</button>
            <Link href={`/avatars/${encodeURIComponent(createdAvatar.avatar_id)}`}>查看 Avatar</Link>
            <button type="button" onClick={() => changeTask("action")}><Film aria-hidden="true" />继续创建动作</button>
          </div>
        </section>
      ) : null}

      {previewOpen && previewImageUrl ? (
        <div className={styles.previewBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setPreviewOpen(false); }}>
          <section className={styles.previewDialog} role="dialog" aria-modal="true" aria-label={`${previewDisplayName} 大图预览`}>
            <header><div><span>Avatar Preview</span><strong>{previewDisplayName}</strong></div><button type="button" autoFocus aria-label="关闭 Avatar 预览" onClick={() => setPreviewOpen(false)}><X /></button></header>
            <div>
              <Image className={styles.previewBackdropImage} src={previewImageUrl} alt="" aria-hidden="true" fill sizes="100vw" unoptimized />
              <Image className={styles.previewPortraitImage} src={previewImageUrl} alt={`${previewDisplayName} 完整预览`} fill sizes="100vw" unoptimized />
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("图片读取失败"));
    reader.onload = () => typeof reader.result === "string" ? resolve(reader.result) : reject(new Error("图片读取失败"));
    reader.readAsDataURL(file);
  });
}

export function isAvatarNameLocked(mode: "library" | "upload" | "happyimage") {
  return mode === "library";
}

async function imageUrlToFile(imageUrl: string, displayName: string) {
  const response = await fetch(imageUrl);
  if (!response.ok) throw new Error("Avatar 源图读取失败");
  const blob = await response.blob();
  return new File([blob], `${displayName}.jpg`, { type: blob.type || "image/jpeg" });
}

function suggestNextNumberedAvatarName(displayNames: string[]) {
  let highestNumber = 0;
  for (const displayName of displayNames) {
    const match = /^数字人(\d+)$/.exec(displayName.trim());
    if (match) highestNumber = Math.max(highestNumber, Number(match[1]));
  }
  return `数字人${highestNumber + 1}`;
}

