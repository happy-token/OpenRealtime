"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { ArrowLeft, Film, LoaderCircle, Maximize2, Minimize2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { AvatarActionStudio } from "@/components/avatar/avatar-action-studio";
import { PersonalVideoGeneration } from "@/components/settings/personal-video-generation";
import { fetchOwnedAvatar } from "@/lib/avatar-catalog-client";
import type { OwnedAvatarActionRecord, OwnedAvatarRecord } from "@/lib/avatar-records";
import { completeRoleCreationResource } from "./role-creation-workbench-context";
import styles from "./role-action-composer.module.css";

export function RoleActionComposer({
  avatarId,
  presentation,
  returnTo,
}: {
  avatarId: string;
  presentation: "window" | "page";
  returnTo?: string;
}) {
  const router = useRouter();
  const [avatar, setAvatar] = useState<OwnedAvatarRecord | null>(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [error, setError] = useState("");
  const [maximized, setMaximized] = useState(false);
  const personal = avatarId.startsWith("avatar-personal-");

  useEffect(() => {
    if (!avatarId) {
      setError("缺少需要创建动作的数字人形象");
      return;
    }
    const controller = new AbortController();
    void fetchOwnedAvatar(avatarId, controller.signal)
      .then((record) => {
        if (!record) throw new Error("找不到当前数字人形象");
        setAvatar(record);
      })
      .catch((cause) => {
        if (cause instanceof Error && cause.name === "AbortError") return;
        setError(cause instanceof Error ? cause.message : "数字人形象读取失败");
      });
    return () => controller.abort();
  }, [avatarId]);

  const close = useCallback(() => {
    if (returnTo) {
      router.replace(`/roles/${encodeURIComponent(returnTo)}`);
      return;
    }
    if (presentation === "window") router.back();
    else router.replace("/roles/new");
  }, [presentation, returnTo, router]);

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
      if (event.key === "Escape") close();
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
  }, [close, presentation]);

  function finish(action: OwnedAvatarActionRecord) {
    if (returnTo) {
      window.sessionStorage.setItem("openrealtime:role-create-notice", "新动作已创建并选中");
      router.replace(`/roles/${encodeURIComponent(returnTo)}`);
      return;
    }
    completeRoleCreationResource({ kind: "action", id: action.avatar_action_id });
    close();
  }

  const content = <section
    className={styles.window}
    data-presentation={presentation}
    data-maximized={maximized}
    role={presentation === "window" ? "dialog" : undefined}
    aria-modal={presentation === "window" ? "true" : undefined}
    aria-labelledby="role-action-composer-title"
  >
    <header className={styles.titlebar}>
      <button type="button" onClick={close} aria-label="返回创建任务"><ArrowLeft /></button>
      <div><small>CREATE ROLE · AVATAR ACTION</small><strong id="role-action-composer-title">新建动作底片</strong></div>
      <span><Film />动作创作</span>
      {presentation === "window" ? <button type="button" onClick={() => setMaximized((value) => !value)} aria-label={maximized ? "还原窗口" : "最大化窗口"}>{maximized ? <Minimize2 /> : <Maximize2 />}</button> : null}
      <button type="button" onClick={close} aria-label="关闭动作工作台"><X /></button>
    </header>

    <div className={styles.body} data-personal={personal}>
      {error ? <div className={styles.state} role="alert"><Film /><strong>动作工作台暂不可用</strong><p>{error}</p><button type="button" onClick={close}>返回创建任务</button></div>
        : !avatar ? <div className={styles.state} role="status"><LoaderCircle /><strong>正在准备动作工作台</strong><p>读取当前形象与已有动作。</p></div>
          : personal ? <>
            <section className={styles.personalStage} aria-label="当前数字人和动作预览">
              {previewUrl ? <video src={previewUrl} controls autoPlay muted loop playsInline /> : <>
                <Image className={styles.stageBackdrop} src={avatar.source_image_url} alt="" fill sizes="70vw" unoptimized aria-hidden="true" />
                <Image className={styles.stageImage} src={avatar.source_image_url} alt={`${avatar.display_name}形象预览`} fill sizes="70vw" unoptimized priority />
              </>}
              <div className={styles.stageShade} />
              <div className={styles.stageCaption}><span>PERSONAL AVATAR</span><h1>{avatar.display_name}</h1><p>{previewUrl ? "预览生成结果，确认后保存并返回角色任务。" : "当前形象已经锁定，动作会保存到这个形象下面。"}</p></div>
            </section>
            <aside className={styles.personalConfig} aria-label="个人动作生成配置">
              <PersonalVideoGeneration initialAvatarId={avatarId} embedded onPreviewChange={setPreviewUrl} onActionSaved={finish} />
            </aside>
          </> : <div className={styles.sharedStudio}>
            <AvatarActionStudio
              avatarId={avatarId}
              embedded
              previewImageUrl={avatar.source_image_url}
              configHeader={<div className={styles.contextCard}><span>当前形象</span><strong>{avatar.display_name}</strong><small>动作保存后会自动回填{ returnTo ? "角色设置" : "角色创建任务" }。</small></div>}
              onSaved={finish}
            />
          </div>}
    </div>
  </section>;

  return presentation === "window"
    ? <div className={styles.backdrop}>{content}</div>
    : <main className={styles.page}>{content}</main>;
}
