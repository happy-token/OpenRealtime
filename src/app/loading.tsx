import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import styles from "./loading.module.css";

export default function Loading() {
  return <WorkspaceShell>
    <div className={styles.loadingContent} role="status" aria-label="正在切换页面">
      <span className={styles.indicator} aria-hidden="true" />
    </div>
  </WorkspaceShell>;
}
