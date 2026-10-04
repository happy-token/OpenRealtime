"use client";

import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { useLanguage } from "@/components/language/language-provider";
import { SelectMenu } from "@/components/ui/select-menu";
import { fetchRoles } from "@/lib/role-catalog-client";
import { readJsonResponse } from "@/lib/http-json-response";
import { TOOL_PERMISSION_OPTIONS, effectiveToolPermission, type ToolPermissionMode, type ToolPermissionSettings } from "@/lib/tool-permission-types";
import styles from "./tool-permissions-screen.module.css";

export function ToolPermissionsScreen() {
  const { t } = useLanguage();
  const [settings, setSettings] = useState<ToolPermissionSettings | null>(null);
  const [roles, setRoles] = useState<{ id: string; name: string }[]>([]);
  const [selectedRole, setSelectedRole] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    setSettings(null);
    const linkedRole = new URLSearchParams(window.location.search).get("roleId") || "";
    if (linkedRole) setSelectedRole(linkedRole);
    void fetch("/api/tool-permissions", { cache: "no-store", signal: controller.signal }).then(async (response) => {
      const payload = await readJsonResponse<ToolPermissionSettings & { error?: string }>(response, "工具权限读取失败");
      if (!response.ok) throw new Error(payload.error || "工具权限读取失败");
      if (!controller.signal.aborted) setSettings(payload);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "工具权限读取失败");
    });
    void fetchRoles(controller.signal).then((items) => {
      if (!controller.signal.aborted) setRoles(items.map((role) => ({ id: role.role_id, name: role.display_name })));
    }).catch(() => {
      if (!controller.signal.aborted) setStatus("角色列表暂时不可用，仍可设置全局权限。");
    });
    return () => controller.abort();
  }, [refresh]);

  async function save(mode: ToolPermissionMode | null, roleId?: string) {
    if (busy || !settings) return;
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const response = await fetch("/api/tool-permissions", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, roleId: roleId ?? null }),
      });
      const payload = await readJsonResponse<ToolPermissionSettings & { error?: string }>(response, "工具权限保存失败");
      if (!response.ok) throw new Error(payload.error || "工具权限保存失败");
      setSettings(payload);
      setStatus("已保存，对后续工具调用生效。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "工具权限保存失败"); }
    finally { setBusy(false); }
  }

  const knownRoles = new Map(roles.map((role) => [role.id, role.name]));
  for (const id of Object.keys(settings?.roleOverrides ?? {})) if (!knownRoles.has(id)) knownRoles.set(id, id);
  if (selectedRole && !knownRoles.has(selectedRole)) knownRoles.set(selectedRole, selectedRole);
  const roleMode = settings && selectedRole && Object.hasOwn(settings.roleOverrides, selectedRole)
    ? settings.roleOverrides[selectedRole] : "inherit";
  const effective = settings ? effectiveToolPermission(settings, selectedRole) : null;

  return <div className={styles.page}>
    <h1><ShieldCheck aria-hidden="true" />{t("工具权限")}</h1>
    <p className={styles.intro}>{t("提前授权工具，减少语音交流中的确认。新用户默认全面开启，所有角色继承全局设置。")}</p>
    {error ? <p role="alert" className={styles.error}>{t(error)}{!settings ? <button onClick={() => setRefresh((value) => value + 1)}>{t("重试")}</button> : null}</p> : null}
    <section className={styles.section} aria-labelledby="tool-permission-global-title">
      <h2 id="tool-permission-global-title">{t("全局权限模式")}</h2>
      {!settings && !error ? <p role="status">{t("正在读取权限设置…")}</p> : null}
      <div className={styles.globalMode}>
        <SelectMenu fullWidth triggerContent={!settings ? t("尚未读取权限模式") : undefined} value={settings?.mode ?? ""} ariaLabel={t("全局权限模式")} disabled={busy || !settings} options={TOOL_PERMISSION_OPTIONS.map((option) => ({ value: option.value, label: t(option.label) }))} onChange={(value) => void save(value as ToolPermissionMode)} />
      </div>
      {settings ? <p className={styles.note}>{t(TOOL_PERMISSION_OPTIONS.find((option) => option.value === settings.mode)!.description)}</p> : null}
      <p className={styles.note}>{t("自动授权仅适用于当前用户有权使用且已启用的工具。工具和知识库的访问范围仍由账户与角色决定。")}</p>
    </section>
    <section className={styles.section} aria-labelledby="tool-permission-role-title">
      <h2 id="tool-permission-role-title">{t("角色权限")}</h2>
      <p className={styles.note}>{t("角色可以单独设置权限，也可以随时恢复为继承全局。")}</p>
      <div className={styles.fields}>
        <label>{t("角色")}<SelectMenu fullWidth value={selectedRole} ariaLabel={t("选择权限角色")} disabled={busy || !settings} options={[{ value: "", label: t("选择角色") }, ...Array.from(knownRoles, ([value, label]) => ({ value, label }))]} onChange={setSelectedRole} /></label>
        <label>{t("权限模式")}<SelectMenu fullWidth value={roleMode} ariaLabel={t("角色权限模式")} disabled={busy || !settings || !selectedRole} options={[{ value: "inherit", label: t("继承全局") }, ...TOOL_PERMISSION_OPTIONS.map((option) => ({ value: option.value, label: t(option.label) }))]} onChange={(value) => void save(value === "inherit" ? null : value as ToolPermissionMode, selectedRole)} /></label>
      </div>
      {selectedRole && effective ? <p className={styles.note}>{t("当前生效")}: {t(TOOL_PERMISSION_OPTIONS.find((option) => option.value === effective)!.label)}</p> : null}
    </section>
    <p role="status" aria-live="polite" className={styles.status}>{busy ? t("正在保存…") : t(status)}</p>
    <p className={styles.note}>{t("已在等待确认的操作仍需处理；新模式从后续工具调用开始生效。")}</p>
  </div>;
}
