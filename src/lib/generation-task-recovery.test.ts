import { describe, expect, it } from "vitest";
import {
  clearRecoverableGenerationTask,
  readRecoverableGenerationTask,
  saveRecoverableGenerationTask,
  shouldRecoverGenerationSubmission,
} from "./generation-task-recovery";

function storage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  };
}

describe("generation task recovery", () => {
  it("restores an in-flight task after a page refresh", () => {
    const local = storage();
    saveRecoverableGenerationTask({
      avatarId: "avatar-1",
      purpose: "action",
      requestId: "request-1",
      provider: "minimax",
      taskId: "task-1",
      displayName: "忧郁共鸣",
      sourceId: "melancholy-empathy",
      startedAt: 1_000,
    }, local);
    expect(readRecoverableGenerationTask("avatar-1", "action", local, 2_000)).toMatchObject({
      requestId: "request-1",
      taskId: "task-1",
      provider: "minimax",
      displayName: "忧郁共鸣",
      sourceId: "melancholy-empathy",
    });
  });

  it("drops malformed and expired recovery handles", () => {
    const local = storage();
    local.setItem("openrealtime:generation-task:avatar-1", "{broken");
    expect(readRecoverableGenerationTask("avatar-1", "action", local)).toBeUndefined();
    saveRecoverableGenerationTask({
      avatarId: "avatar-1",
      purpose: "action",
      requestId: "request-1",
      provider: "ltx",
      startedAt: 1,
    }, local);
    expect(readRecoverableGenerationTask("avatar-1", "action", local, 8 * 24 * 60 * 60 * 1_000)).toBeUndefined();
  });

  it("clears a task after the generated action is saved or discarded", () => {
    const local = storage();
    saveRecoverableGenerationTask({
      avatarId: "avatar-1",
      purpose: "action",
      requestId: "request-1",
      provider: "liveportrait",
      taskId: "task-1",
      startedAt: Date.now(),
    }, local);
    clearRecoverableGenerationTask("avatar-1", "action", local);
    expect(readRecoverableGenerationTask("avatar-1", "action", local)).toBeUndefined();
  });

  it("does not start refresh recovery while the original paid submission is still running", () => {
    expect(shouldRecoverGenerationSubmission({
      requestId: "request-1",
      taskId: "",
      provider: "minimax",
      taskState: "queueing",
      submissionInFlight: true,
    })).toBe(false);
    expect(shouldRecoverGenerationSubmission({
      requestId: "request-1",
      taskId: "",
      provider: "minimax",
      taskState: "queueing",
      submissionInFlight: false,
    })).toBe(true);
  });
});
