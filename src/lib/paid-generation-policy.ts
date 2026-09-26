import path from "node:path";

/** Production paid jobs require an operator-approved durable ledger location. */
export function paidGenerationEnabled(environment: NodeJS.ProcessEnv = process.env) {
  if (environment.NODE_ENV !== "production") return true;
  return environment.OPENREALTIME_PAID_GENERATION_ENABLED === "true"
    && Boolean(environment.OPENREALTIME_GENERATION_TASKS_PATH)
    && path.isAbsolute(environment.OPENREALTIME_GENERATION_TASKS_PATH || "")
    && Boolean(environment.MINIMAX_UPLOAD_CACHE_PATH)
    && path.isAbsolute(environment.MINIMAX_UPLOAD_CACHE_PATH || "");
}
