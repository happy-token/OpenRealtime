import { mkdir, rmdir } from "node:fs/promises";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";

/** Serialize catalog transactions across processes sharing one persistent directory. */
export async function withAvatarCatalogLock<T>(
  root: string,
  task: () => Promise<T>,
  timeoutMs = 5_000,
): Promise<T> {
  await mkdir(root, { recursive: true });
  const lockPath = path.join(root, ".catalog-lock");
  const deadline = performance.now() + timeoutMs;
  for (;;) {
    try {
      await mkdir(lockPath);
      break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      if (performance.now() >= deadline) {
        throw new Error("Avatar 目录正被占用，请稍后重试；若进程异常退出，请管理员检查目录锁");
      }
      await delay(Math.min(25, Math.max(1, deadline - performance.now())));
    }
  }
  try {
    return await task();
  } finally {
    // Never steal a lock based on age: a slow writer may still own it.
    await rmdir(lockPath);
  }
}
