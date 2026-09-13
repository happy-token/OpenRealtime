import { describe, expect, it } from "vitest";
import {
  CONNECTION_STATUS_LABELS,
  resolveSessionStatusLabel,
} from "./session-copy";

describe("session copy", () => {
  it("describes microphone state without implying the whole session is paused", () => {
    expect(resolveSessionStatusLabel({ state: "speaking", microphoneMuted: true })).toBe("麦克风已关闭");
    expect(resolveSessionStatusLabel({ state: "speaking" })).toBe("正在回答");
  });

  it("gives the ended state priority and only claims recovery while reconnecting", () => {
    expect(resolveSessionStatusLabel({ state: "listening", microphoneMuted: true, ended: true })).toBe("本次对话已结束");
    expect(CONNECTION_STATUS_LABELS.reconnecting).toBe("连接中断，正在恢复…");
    expect(CONNECTION_STATUS_LABELS.error).toBe("连接未恢复");
  });
});
