"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { DEFAULT_CONVERSATION_PREFERENCES, readConversationPreferences, writeConversationPreferences } from "@/lib/conversation-preferences";
import styles from "./appearance-settings-screen.module.css";

export function AdvancedSettingsScreen() {
  const [settings, setSettings] = useState(DEFAULT_CONVERSATION_PREFERENCES);
  useEffect(() => setSettings(readConversationPreferences()), []);
  function update(next: typeof settings) { setSettings(next); writeConversationPreferences(next); }

  return <div className={styles.page}>
    <h1 className={styles.pageTitle}>高级配置</h1>
    <p className={styles.intro}>调整新对话的本地播放与收音默认值。</p>
    <section className={styles.section}>
      <h2>对话设备</h2>
      <label className={styles.range}><span>本地播放音量 <strong>{settings.volume}%</strong></span><input type="range" min="0" max="100" value={settings.volume} onChange={(event) => update({ ...settings, volume: Number(event.target.value) })} /></label>
      <label className={styles.toggle}><span>允许随时打断</span><input type="checkbox" checked={settings.allowBargeIn} onChange={(event) => update({ ...settings, allowBargeIn: event.target.checked })} /></label>
      <label className={styles.toggle}><span>浏览器降噪与回声消除</span><input type="checkbox" checked={settings.noiseSuppression} onChange={(event) => update({ ...settings, noiseSuppression: event.target.checked })} /></label>
    </section>
    <section className={styles.section}><h2>角色与工具</h2><p>声音、Persona 和对话能力随角色配置；共享工具在资源库管理。</p><div className={styles.optionGrid}><Link href="/roles">角色配置</Link><Link href="/resources?tab=tools">工具资源库</Link></div></section>
  </div>;
}
