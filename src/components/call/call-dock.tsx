"use client";

import { useLanguage } from "@/components/language/language-provider";


import { useState } from "react";
import { Icon } from "@/components/ui/icons";
import { MicButton } from "@/components/ui/mic-button";

interface CallDockProps {
  micActive: boolean;
  connected: boolean;
  onToggleMic: () => void;
  onSendText: (text: string) => void;
  onShowChat: () => void;
}

export function CallDock({ micActive, connected, onToggleMic, onSendText, onShowChat }: CallDockProps) {
  const { t } = useLanguage();
  const [textMode, setTextMode] = useState(false);
  const [text, setText] = useState("");

  function submitText(event: React.FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value) return;
    onSendText(value);
    setText("");
  }

  return (
    <div className="call-dock">
      {textMode ? (
        <form className="text-row" onSubmit={submitText}>
          <button
            type="button"
            className="text-mode-back"
            aria-label={t("返回语音控制")}
            onClick={() => setTextMode(false)}
          >
            <Icon name="arrow-left" />
            <span>{t("返回语音")}</span>
          </button>
          <input
            type="text"
            placeholder={t("输入文字…")}
            autoComplete="off"
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <button type="submit" className="text-row-send" aria-label={t("发送文字消息")}>
            <Icon name="send" />
            <span>{t("发送")}</span>
          </button>
        </form>
      ) : (
        <div className="voice-row">
          <button
            type="button"
            className="dock-action"
            aria-label={t("切换到文字输入")}
            onClick={() => setTextMode(true)}
          >
            <Icon name="keyboard" />
            <span>{t("文字输入")}</span>
          </button>
          <div className="dock-main-wrap">
            <MicButton
              className="dock-btn dock-main"
              active={micActive}
              connected={connected}
              onClick={onToggleMic}
            />
            <span className="dock-main-label">{micActive ? t("结束通话") : t("开始对话")}</span>
          </div>
          <button
            type="button"
            className="dock-action"
            aria-label={t("查看对话记录")}
            onClick={onShowChat}
          >
            <Icon name="list" />
            <span>{t("对话记录")}</span>
          </button>
        </div>
      )}
    </div>
  );
}
