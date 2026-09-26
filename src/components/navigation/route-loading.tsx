import styles from "@/app/loading.module.css";

export function RouteLoading() {
  return <div className={styles.loading} role="status" aria-label="正在切换页面">
    <span className={styles.indicator} aria-hidden="true" />
  </div>;
}
