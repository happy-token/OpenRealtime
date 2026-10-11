"use client";
import { LocalizedText } from "@/components/language/language-provider";

import { useLanguage } from "@/components/language/language-provider";


import { Check, CircleAlert, LoaderCircle, Search } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { AnamHostedAvatar } from "@/lib/anam-avatars";
import { readJsonResponse } from "@/lib/http-json-response";

type CatalogPhase = "loading" | "ready" | "error";

interface HostedAvatarCatalogProps {
  active: boolean;
  disabled: boolean;
  selectedAvatarId: string;
  onSelect: (avatar: AnamHostedAvatar | { id: "default-anam"; displayName: string; imageUrl: string }) => void;
}

const ENVIRONMENT_AVATAR = {
  id: "default-anam" as const,
  displayName: "当前环境形象",
  imageUrl: "",
};

export function HostedAvatarCatalog({ active, disabled, selectedAvatarId, onSelect }: HostedAvatarCatalogProps) {
  const { t } = useLanguage();
  const [avatars, setAvatars] = useState<AnamHostedAvatar[]>([]);
  const [phase, setPhase] = useState<CatalogPhase>("loading");
  const [notice, setNotice] = useState("正在读取可用形象");
  const [providerDefaultId, setProviderDefaultId] = useState("");
  const [search, setSearch] = useState("");
  const [showAllOfficial, setShowAllOfficial] = useState(false);

  const loadCatalog = useCallback(async () => {
    setPhase("loading");
    setNotice("正在读取可用形象");
    try {
      const response = await fetch("/api/anam/avatars", { cache: "no-store" });
      const payload = await readJsonResponse<{
        avatars?: AnamHostedAvatar[];
        defaultAvatarId?: string | null;
        error?: string;
      }>(response, "数字人形象目录请求失败");
      if (!response.ok) throw new Error(payload.error || "形象资产库读取失败");
      setAvatars(payload.avatars ?? []);
      setProviderDefaultId(payload.defaultAvatarId ?? "");
      setPhase("ready");
      setNotice(`已加载 ${payload.avatars?.length ?? 0} 个可用形象`);
    } catch (error) {
      setPhase("error");
      setNotice(error instanceof Error ? error.message : "形象资产库读取失败");
    }
  }, []);

  useEffect(() => {
    if (active) void loadCatalog();
  }, [active, loadCatalog]);

  const searchTerm = search.trim().toLocaleLowerCase();
  const matchesSearch = (avatar: AnamHostedAvatar) => !searchTerm
    || avatar.displayName.toLocaleLowerCase().includes(searchTerm)
    || avatar.displayTags.some((tag) => tag.toLocaleLowerCase().includes(searchTerm));
  const personal = avatars.filter((avatar) => avatar.origin === "personal" && matchesSearch(avatar));
  const allOfficial = avatars.filter((avatar) => avatar.origin === "official" && matchesSearch(avatar));
  const official = showAllOfficial || searchTerm ? allOfficial : allOfficial.slice(0, 18);
  const effectiveSelectedAvatarId = selectedAvatarId === "default-anam" && providerDefaultId
    ? providerDefaultId
    : selectedAvatarId;
  const providerDefaultResolved = Boolean(providerDefaultId && avatars.some((avatar) => avatar.id === providerDefaultId));

  return (
    <div className="hosted-avatar-catalog">
      <div className="avatar-asset-library-toolbar">
        <label className="hosted-avatar-search">
          <Search aria-hidden="true" />
          <input value={search} aria-label={t("搜索数字人形象")} placeholder={t("搜索名称或标签")} onChange={(event) => setSearch(event.target.value)} />
        </label>
        <span className="avatar-asset-library-status" data-state={phase} role="status">
          {phase === "loading" ? <LoaderCircle /> : phase === "error" ? <CircleAlert /> : <i />}
          {t(notice)}
        </span>
      </div>

      <HostedAvatarGroup
        title={t("我的形象")}
        description={t("已经创建并可用于实时托管的形象")}
        avatars={personal}
        selectedAvatarId={effectiveSelectedAvatarId}
        disabled={disabled}
        emptyLabel={t("当前没有可用的个人形象")}
        onSelect={onSelect}
        prefix={providerDefaultResolved ? undefined : <HostedAvatarCard avatar={ENVIRONMENT_AVATAR} selected={selectedAvatarId === ENVIRONMENT_AVATAR.id} disabled={disabled} onSelect={() => onSelect(ENVIRONMENT_AVATAR)} />}
      />
      <HostedAvatarGroup
        title={t("内置形象")}
        description={t("平台提供、已经可以直接使用的参考形象")}
        avatars={official}
        selectedAvatarId={effectiveSelectedAvatarId}
        disabled={disabled}
        emptyLabel={phase === "error" ? "暂时无法读取内置形象" : "没有匹配的内置形象"}
        onSelect={onSelect}
      />
      {!searchTerm && allOfficial.length > official.length && <button className="hosted-avatar-show-all" type="button" onClick={() => setShowAllOfficial(true)}>{t("显示全部 ")}{allOfficial.length}{t(" 个内置形象")}</button>}
    </div>
  );
}

function HostedAvatarGroup({ title, description, avatars, selectedAvatarId, disabled, emptyLabel, onSelect, prefix }: {
  title: string;
  description: string;
  avatars: AnamHostedAvatar[];
  selectedAvatarId: string;
  disabled: boolean;
  emptyLabel: string;
  onSelect: HostedAvatarCatalogProps["onSelect"];
  prefix?: React.ReactNode;
}) {
  const { t } = useLanguage();
  return (
    <section className="hosted-avatar-group">
      <header><div><strong>{<LocalizedText text={title} />}</strong><small>{<LocalizedText text={description} />}</small></div><em>{avatars.length + (prefix ? 1 : 0)}{t(" 个")}</em></header>
      <div className="avatar-library-grid">
        {prefix}
        {avatars.map((avatar) => <HostedAvatarCard key={avatar.id} avatar={avatar} selected={selectedAvatarId === avatar.id} disabled={disabled} onSelect={() => onSelect(avatar)} />)}
      </div>
      {!avatars.length && !prefix && <p>{emptyLabel}</p>}
    </section>
  );
}

function HostedAvatarCard({ avatar, selected, disabled, onSelect }: {
  avatar: Pick<AnamHostedAvatar, "id" | "displayName" | "imageUrl">;
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
  const { t } = useLanguage();
  return (
    <button type="button" data-selected={selected} aria-pressed={selected} disabled={disabled} onClick={onSelect}>
      <span className="avatar-library-visual hosted-avatar-preview" style={avatar.imageUrl ? { backgroundImage: `url("${avatar.imageUrl.replaceAll('"', "%22")}")` } : undefined}><span className="sr-only">{<LocalizedText text={avatar.displayName} />}{t(" 预览")}</span></span>
      <span><strong>{<LocalizedText text={avatar.displayName} />}</strong><small>{avatar.id === "default-anam" ? t("当前使用") : t("实时托管")}</small></span>
      <i>{selected ? <Check /> : null}</i>
    </button>
  );
}
