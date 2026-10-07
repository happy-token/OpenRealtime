import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { SessionRecordings } from "./session-recordings";

it("offers independent recording access with explicit evidence limits", () => {
  const html = renderToStaticMarkup(<SessionRecordings sessionId="session" />);
  expect(html).toContain("查看录音"); expect(html).toContain("已发送不代表已播放");
  expect(html).toContain("片段可能因采集或存储异常缺失");
  expect(html).not.toContain("<audio"); expect(html).not.toContain("autoplay");
});
it("disables live recording access in preview", () => {
  const html = renderToStaticMarkup(<SessionRecordings sessionId="session" preview />);
  expect(html).toMatch(/<button disabled="">查看录音<\/button>/);
  expect(html).toContain("预览页面不读取真实录音");
});
