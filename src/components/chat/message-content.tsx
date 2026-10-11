"use client";
import { useLanguage } from "@/components/language/language-provider";

import { LocalizedText } from "@/components/language/language-provider";
import type { ComponentProps } from "react";
import { memo } from "react";
import Markdown, { defaultUrlTransform, type Components } from "react-markdown";
import remend from "remend";
import remarkGfm from "remark-gfm";

function MessageLink({ node, href, ...props }: ComponentProps<"a"> & { node?: unknown }) {
  void node;
  const external = typeof href === "string" && /^https?:\/\//i.test(href);

  return (
    <a
      {...props}
      href={href}
      {...(external ? { target: "_blank", rel: "noreferrer noopener" } : {})}
    />
  );
}

function MessageImage({ node, alt, src, ...props }: ComponentProps<"img"> & { node?: unknown }) {
  void node;
  if (typeof src === "string" && /^https?:\/\//i.test(src)) {
    return (
      <a
        className="message-image-link"
        href={src}
        target="_blank"
        rel="noreferrer noopener"
      >
        {<LocalizedText text={"查看外部图片："} />}{alt || "对话图片"}
      </a>
    );
  }
  return (
    // Only deployment-local Markdown images reach this branch. Remote images
    // stay as explicit links above so model output cannot trigger tracking
    // requests without a user action.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      {...props}
      src={src}
      alt={alt || "对话图片"}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
    />
  );
}

function MessageTable({ node, ...props }: ComponentProps<"table"> & { node?: unknown }) {
  const { t } = useLanguage();
  void node;
  return (
    <div className="message-table-scroll" role="region" aria-label={t("表格内容")} tabIndex={0}>
      <table {...props} />
    </div>
  );
}

const MARKDOWN_COMPONENTS: Components = {
  a: MessageLink,
  img: MessageImage,
  table: MessageTable,
};
const MARKDOWN_PLUGINS = [remarkGfm];

interface MessageContentProps {
  text: string;
}

export const MessageContent = memo(function MessageContent({ text }: MessageContentProps) {
  return (
    <div className="message-markdown">
      <Markdown
        components={MARKDOWN_COMPONENTS}
        remarkPlugins={MARKDOWN_PLUGINS}
        skipHtml
        urlTransform={defaultUrlTransform}
      >
        {remend(text, { inlineKatex: false, katex: false })}
      </Markdown>
    </div>
  );
});
