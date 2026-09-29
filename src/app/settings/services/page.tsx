
import { LocalizedText } from "@/components/language/language-provider";
import type { Metadata } from "next";
import { cookies } from "next/headers";
import { ADMIN_SESSION_COOKIE, adminAuthConfigFromEnv, verifyAdminSessionToken } from "@/lib/admin-auth";
import { ModelServicesSettings } from "@/components/settings/model-services-settings";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import styles from "@/components/settings/provider-settings-screen.module.css";

export const metadata: Metadata = { title: "模型服务 — OpenRealtime" };

export default async function ServicesPage() {
  const config = adminAuthConfigFromEnv();
  const admin = Boolean(config && verifyAdminSessionToken((await cookies()).get(ADMIN_SESSION_COOKIE)?.value, config));
  return <WorkspaceShell><div className={styles.page}>
    <h1 className={styles.pageTitle}>{<LocalizedText text={"模型服务"} />}</h1>
    <p className={styles.intro}>{<LocalizedText text={"配置动作生成与口型服务地址，并测试连接状态。"} />}</p>
    <ModelServicesSettings scope="personal" />
    {admin && <section className={styles.serviceSection}><div className={styles.serviceHeading}>
      <h2>{<LocalizedText text={"平台模型服务"} />}</h2><p>{<LocalizedText text={"管理员维护供全站使用的模型服务。"} />}</p>
    </div><ModelServicesSettings scope="platform" /></section>}
  </div></WorkspaceShell>;
}
