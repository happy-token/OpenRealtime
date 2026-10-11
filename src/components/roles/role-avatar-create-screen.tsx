"use client";

import { useLanguage } from "@/components/language/language-provider";


import { BackLink } from "@/components/workspace/back-link";

import { useRouter } from "next/navigation";
import { LoaderCircle, Upload } from "lucide-react";
import { useState } from "react";
import { readJsonResponse } from "@/lib/http-json-response";
import styles from "./role-avatar-create-screen.module.css";

export function RoleAvatarCreateScreen({ roleId }: { roleId: string }) {
  const { t } = useLanguage();
  const router = useRouter();
  const [name, setName] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    if (!name.trim() || !image || busy) return;
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.set("name", name.trim());
      body.set("image", image);
      const response = await fetch("/api/user/avatars", { method: "POST", body });
      const result = await readJsonResponse<{ avatar?: { avatar_id: string }; error?: string }>(response, "形象创建失败");
      if (!response.ok || !result.avatar) throw new Error(result.error || "形象创建失败");
      router.replace(`/roles/${encodeURIComponent(roleId)}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "形象创建失败");
      setBusy(false);
    }
  }

  return <main className={styles.page}>
    <BackLink href={`/roles/${encodeURIComponent(roleId)}`} label={t("返回当前角色")} />
    <section className={styles.card}>
      <span>{t("数字人形象")}</span>
      <h1>{t("上传角色形象")}</h1>
      <p>{t("上传后会返回角色配置，并选中新形象。动作和口型对齐可以稍后添加。")}</p>
      <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <label htmlFor="avatar-name">{t("形象名称")}</label>
        <input id="avatar-name" value={name} maxLength={50} onChange={(event) => setName(event.target.value)} placeholder={t("例如：产品顾问形象")} />
        <label htmlFor="avatar-image">{t("形象图片")}</label>
        <input id="avatar-image" type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => setImage(event.target.files?.[0] ?? null)} />
        {error ? <p role="alert" className={styles.error}>{t(error)}</p> : null}
        <button type="submit" disabled={busy || !name.trim() || !image}>{busy ? <LoaderCircle /> : <Upload />}{busy ? t("正在上传…") : t("创建形象")}</button>
      </form>
    </section>
  </main>;
}
