"use client";

import { useEffect, useRef } from "react";

const LOGIN_URL = "/api/user/login?next=%2Fsettings%2Fsession-diagnostics";

/** OIDC redirects must navigate a document, rather than fetch an RSC payload. */
export function AdminLoginRedirect() {
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    window.location.replace(LOGIN_URL);
  }, []);

  return <main><p role="status">登录状态已失效，正在前往账号登录…</p>
    <a href={LOGIN_URL}>继续登录并返回会话诊断</a>
  </main>;
}
