import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { freezeSessionTranscript, SessionEndedActions } from "./session-end-review";

describe("session ended experience", () => {
  it("freezes a copy and marks unfinished assistant output as interrupted", () => {
    const source = [{ role: "assistant" as const, text: "还没有说完", status: "streaming" as const }];
    const frozen = freezeSessionTranscript(source);
    expect(frozen).toEqual([{ role: "assistant", text: "还没有说完", status: "interrupted" }]);
    expect(frozen).not.toBe(source);
    expect(frozen[0]).not.toBe(source[0]);
  });

  it("uses the start conversation control for continuing and an icon return action", () => {
    const html = renderToStaticMarkup(<SessionEndedActions connected onContinue={() => {}} onReturnHome={() => {}} />);
    expect(html).toContain("voice-start-halo");
    expect(html).toContain("voice-start-halo--magic-rings");
    expect(html).toContain('aria-label="继续对话"');
    expect(html).toContain("本次对话已结束");
    expect(html).toContain("返回主页");
    expect(html).toContain("lucide-arrow-left");
    expect(html).not.toContain("复制");
    expect(html).not.toContain("对话记录");
  });

});
