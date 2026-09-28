"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { HomePreviewWorkspace } from "@/components/call/home-preview-workspace";
import { DEFAULT_AVATAR_DISPLAY_CONFIG, parseAvatarDisplayConfig, type AvatarDisplayConfig } from "@/components/digital-human/types";
import { AVATAR_DISPLAY_CONFIG_STORAGE_KEY } from "@/lib/avatar-identity-sync";
import { avatarResourceHref, type AvatarWorkbenchLocation, type AvatarWorkbenchTask } from "@/lib/avatar-workbench-navigation";
import { AvatarProductionOverlay } from "./avatar-production-overlay";
import { AvatarUploadDialog, createdAvatarDisplayConfig } from "./avatar-upload-dialog";

const LIBRARY_DEFAULT_CONFIG: AvatarDisplayConfig = {
  ...DEFAULT_AVATAR_DISPLAY_CONFIG,
  renderPath: "segmented",
};

export function AvatarResourceHome({
  task,
  avatarId,
  actionId,
  method,
  returnToRoleId,
}: {
  task?: AvatarWorkbenchTask;
  avatarId?: string;
  actionId?: string;
  method?: "lipforcing";
  returnToRoleId?: string;
}) {
  const router = useRouter();
  const [config, setConfig] = useState<AvatarDisplayConfig>(LIBRARY_DEFAULT_CONFIG);
  const [catalogRevision, setCatalogRevision] = useState(0);
  const [stagePreview, setStagePreview] = useState<{ url: string; name: string; kind?: "talking" } | null>(null);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(AVATAR_DISPLAY_CONFIG_STORAGE_KEY);
      if (saved) setConfig(parseAvatarDisplayConfig(JSON.parse(saved)));
    } catch {
      // The shared library remains usable with the built-in default.
    }
  }, []);

  function updateConfig(next: AvatarDisplayConfig) {
    setStagePreview(null);
    setConfig(next);
    window.localStorage.setItem(AVATAR_DISPLAY_CONFIG_STORAGE_KEY, JSON.stringify(next));
  }

  function openProduction(location: AvatarWorkbenchLocation) {
    router.replace(avatarResourceHref({ ...location, returnTo: returnToRoleId }), { scroll: false });
  }

  function closeProduction() {
    setStagePreview(null);
    router.replace(avatarResourceHref({ returnTo: returnToRoleId }), { scroll: false });
  }

  const updateStagePreview = useCallback((preview: { url: string; name: string; kind?: "talking" } | null) => {
    setStagePreview(preview);
  }, []);

  return <>
    <HomePreviewWorkspace
      purpose="library"
      connected
      error={null}
      visualTheme="liquid-glass"
      experienceMode="avatar"
      avatarDisplayConfig={config}
      reducedMotion={false}
      onVisualThemeChange={() => undefined}
      onExperienceModeChange={() => undefined}
      onAvatarDisplayConfigChange={updateConfig}
      onStartSession={() => undefined}
      onOpenProduction={openProduction}
      catalogRevision={catalogRevision}
      stagePreview={stagePreview}
      collapseResourceRails={task === "motion" || task === "talking" || task === "realtime"}
    />
    {task === "avatar" || task === "realtime" ? <AvatarUploadDialog
      mode={task}
      onClose={closeProduction}
      onCreated={(avatar) => {
        updateConfig(createdAvatarDisplayConfig(config, avatar));
        setCatalogRevision((revision) => revision + 1);
        closeProduction();
      }}
      onRealtimeCreated={() => { setCatalogRevision((revision) => revision + 1); closeProduction(); }}
    /> : task ? <AvatarProductionOverlay
      task={task}
      avatarId={avatarId}
      actionId={actionId}
      method={method}
      returnToRoleId={returnToRoleId}
      onClose={closeProduction}
      onPreviewChange={task === "motion" || task === "talking" ? updateStagePreview : undefined}
      onComplete={(result) => {
        if (task === "motion" && result.actionId) {
          updateConfig({
            ...config,
            renderPath: "segmented",
            segmentedPresetId: "custom-upload",
            segmentedAvatarId: result.avatarId,
            segmentedAvatarActionId: result.actionId,
            motionTalkingVariantId: undefined,
          });
        }
        if (task === "talking" && result.actionId && result.variantId) {
          updateConfig({
            ...config,
            renderPath: "segmented",
            segmentedPresetId: "custom-upload",
            segmentedAvatarId: result.avatarId,
            segmentedAvatarActionId: result.actionId,
            motionTalkingVariantId: result.variantId,
          });
        }
        setCatalogRevision((revision) => revision + 1);
        closeProduction();
      }}
    /> : null}
  </>;
}
