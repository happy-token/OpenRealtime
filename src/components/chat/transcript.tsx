"use client";
import { useLanguage } from "@/components/language/language-provider";

import { LocalizedText } from "@/components/language/language-provider";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown } from "lucide-react";
import type { TranscriptEntry } from "@/hooks/use-voice-session";
import { markdownToSpeechText } from "@/lib/message-text";
import { MessageContent } from "./message-content";

interface TranscriptProps {
  entries: TranscriptEntry[];
  active?: boolean;
}

export function Transcript({ entries, active = true }: TranscriptProps) {
  const { t } = useLanguage();
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const [showLatestButton, setShowLatestButton] = useState(false);
  const latestCompletedAssistant = entries.findLast(
    (entry) => entry.role === "assistant" && entry.status === "completed",
  );

  const scrollToLatest = useCallback((behavior: ScrollBehavior = "smooth") => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottomRef.current = true;
    setShowLatestButton(false);
    el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);

  const updateScrollIntent = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 72;
    stickToBottomRef.current = nearBottom;
    setShowLatestButton(!nearBottom);
  }, []);

  useEffect(() => {
    if (active && stickToBottomRef.current) scrollToLatest("auto");
  }, [active, entries, scrollToLatest]);

  useEffect(() => {
    const content = contentRef.current;
    if (!content || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (active && stickToBottomRef.current) scrollToLatest("auto");
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [active, scrollToLatest]);

  return (
    <div className="transcript-shell">
      <div
        className="transcript"
        ref={scrollRef}
        role="log"
        aria-live="off"
        onScroll={updateScrollIntent}
      >
        <div className="transcript-content" ref={contentRef}>
          {entries.map((entry, index) => (
            <div
              key={`${entry.role}:${entry.turnId ?? entry.generation ?? `local-${index}`}`}
              className={`bubble bubble--${entry.role}`}
              aria-label={entry.role === "user" ? "你" : "助手"}
              data-status={entry.role === "assistant" ? entry.status : undefined}
            >
              {entry.role === "assistant" ? (
                <MessageContent text={entry.text} />
              ) : (
                entry.text
              )}
              {entry.role === "assistant" && entry.status === "interrupted" && (
                <span className="bubble-status">{<LocalizedText text={"回复已中断"} />}</span>
              )}
              {entry.role === "assistant" && entry.status === "failed" && (
                <span className="bubble-status bubble-status--error">{<LocalizedText text={"回复失败"} />}</span>
              )}
            </div>
          ))}
        </div>
      </div>
      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {latestCompletedAssistant
          ? t("助手：{p0}", { p0: String(markdownToSpeechText(latestCompletedAssistant.text)) })
          : ""}
      </p>
      {showLatestButton && (
        <button
          type="button"
          className="transcript-latest-button"
          onClick={() => scrollToLatest()}
          aria-label={t("回到最新消息")}
        >
          <ArrowDown aria-hidden="true" />
          {<LocalizedText text={"最新消息"} />}</button>
      )}
    </div>
  );
}
