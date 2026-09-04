import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Transcript } from "./transcript";

describe("Transcript rich message rendering", () => {
  it("renders assistant GFM, images, links and incomplete streamed emphasis", () => {
    const html = renderToStaticMarkup(
      <Transcript
        entries={[
          {
            role: "assistant",
            generation: 1,
            text: [
              "## 天气详情",
              "",
              "| 城市 | 温度 |",
              "| --- | --- |",
              "| 上海 | 30°C |",
              "",
              "![天气图](/weather.png)",
              "",
              "[查看来源](https://example.com/weather)",
              "",
              "**仍在流式输出",
            ].join("\n"),
          },
        ]}
      />,
    );

    expect(html).toContain("<h2>天气详情</h2>");
    expect(html).toContain("<table>");
    expect(html).toContain('src="/weather.png"');
    expect(html).toContain('loading="lazy"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noreferrer noopener"');
    expect(html).toContain("<strong>仍在流式输出</strong>");
  });

  it("keeps user speech literal and strips unsafe assistant HTML and URLs", () => {
    const html = renderToStaticMarkup(
      <Transcript
        entries={[
          { role: "user", generation: 1, text: "**这是我说出的星号**" },
          {
            role: "assistant",
            generation: 1,
            text: '<script>alert("xss")</script>[危险链接](javascript:alert(1))',
          },
        ]}
      />,
    );

    expect(html).toContain("**这是我说出的星号**");
    expect(html).not.toContain("<script");
    expect(html).not.toContain("javascript:");
  });

  it("does not automatically request remote Markdown images", () => {
    const html = renderToStaticMarkup(
      <Transcript
        entries={[
          {
            role: "assistant",
            generation: 1,
            status: "completed",
            text: "![天气雷达](https://tracker.example/radar.png)",
          },
        ]}
      />,
    );

    expect(html).not.toContain('<img src="https://tracker.example/radar.png"');
    expect(html).toContain('href="https://tracker.example/radar.png"');
    expect(html).toContain("查看外部图片：天气雷达");
  });

  it("labels interrupted replies without announcing every streaming delta", () => {
    const html = renderToStaticMarkup(
      <Transcript
        entries={[
          {
            role: "assistant",
            generation: 1,
            status: "interrupted",
            text: "我查一下，马上",
          },
        ]}
      />,
    );

    expect(html).toContain('data-status="interrupted"');
    expect(html).toContain("回复已中断");
    expect(html).toContain('role="log" aria-live="off"');
  });
});
