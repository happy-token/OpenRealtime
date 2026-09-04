import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ConfirmationCard } from "./confirmation-card";

describe("ConfirmationCard", () => {
  it("renders one exact pending action with explicit approve and reject controls", () => {
    const html = renderToStaticMarkup(
      <ConfirmationCard
        pending={{
          confirmationId: "confirmation-1",
          actionDigest: "a".repeat(64),
          summary: "向外部发送消息",
          requiredChannel: "voice",
          expiresAt: "2026-08-20T12:00:00+00:00",
          generation: 3,
        }}
        onDecision={() => {}}
      />,
    );

    expect(html).toContain("向外部发送消息");
    expect(html).toContain("确认执行");
    expect(html).toContain("拒绝");
    expect(html).toContain('role="alertdialog"');
  });
});
