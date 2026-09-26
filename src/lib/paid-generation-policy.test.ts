import { describe, expect, it } from "vitest";
import { paidGenerationEnabled } from "./paid-generation-policy";

describe("paid generation production gate", () => {
  it("requires explicit opt-in and absolute durable paths in production", () => {
    expect(paidGenerationEnabled({ NODE_ENV: "production" })).toBe(false);
    expect(paidGenerationEnabled({ NODE_ENV: "production", OPENREALTIME_PAID_GENERATION_ENABLED: "true" })).toBe(false);
    expect(paidGenerationEnabled({ NODE_ENV: "production", OPENREALTIME_PAID_GENERATION_ENABLED: "true", OPENREALTIME_GENERATION_TASKS_PATH: "jobs.json", MINIMAX_UPLOAD_CACHE_PATH: "/var/lib/cache.json" })).toBe(false);
    expect(paidGenerationEnabled({ NODE_ENV: "production", OPENREALTIME_PAID_GENERATION_ENABLED: "true", OPENREALTIME_GENERATION_TASKS_PATH: "/var/lib/jobs.json", MINIMAX_UPLOAD_CACHE_PATH: "/var/lib/cache.json" })).toBe(true);
  });
});
