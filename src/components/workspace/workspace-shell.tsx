"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BookOpen,
  Bot,
  ChevronDown,
  ChevronLeft,
  History,
  GitFork,
  Star,
  LibraryBig,
  LogIn,
  LogOut,
  Menu,
  MemoryStick,
  MessageSquarePlus,
  Mic2,
  PanelLeft,
  Palette,
  Search,
  Server,
  Sparkles,
  Settings,
  Settings2,
  SlidersHorizontal,
  UserRound,
  UsersRound,
  Wrench,
  X,
} from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent, type ReactNode } from "react";
import type { RolePresentationMode, RoleRecord } from "@/lib/role-records";
import { listRecentConversationsCached, type RecentConversation } from "@/lib/recent-conversations-client";
import { useOfficialRealtimeAvatars } from "@/hooks/use-official-realtime-avatars";
import { accountIssuerLabel, accountLoginHref, logoutCurrentUser, useCurrentUser } from "@/hooks/use-current-user";
import styles from "./workspace-shell.module.css";

const SIDEBAR_STATE_KEY = "openrealtime-workspace-sidebar-collapsed";

export type SidebarMode = "collapsed" | "preview" | "pinned";
export type SidebarEvent = "hover-enter" | "hover-leave" | "pin" | "collapse";
export type ResourceNavigationTab = "voices" | "personas" | "tools" | "knowledge" | "avatars" | "official-realtime";

export function isResourceWorkspacePath(pathname: string) {
  return pathname.startsWith("/resources")
    || pathname.startsWith("/services/motion")
    || pathname.startsWith("/services/talking");
}

export function transitionSidebarMode(mode: SidebarMode, event: SidebarEvent): SidebarMode {
  if (event === "pin") return "pinned";
  if (event === "collapse") return "collapsed";
  if (event === "hover-enter") return mode === "pinned" ? mode : "preview";
  return mode === "preview" ? "collapsed" : mode;
}

export function WorkspaceShell({
  children,
  session = false,
  immersive = false,
  resourceTab,
  resourceReturnTo,
}: {
  children: ReactNode;
  session?: boolean;
  immersive?: boolean;
  resourceTab?: ResourceNavigationTab;
  resourceReturnTo?: string;
}) {
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const settingsMode = pathname === "/settings" || pathname.startsWith("/settings/");
  const resourceMode = Boolean(resourceTab) || isResourceWorkspacePath(pathname);
  const { configured: realtimeConfigured } = useOfficialRealtimeAvatars(resourceMode);
  const [sidebarMode, setSidebarMode] = useState<SidebarMode>("collapsed");
  const [sidebarReady, setSidebarReady] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [recents, setRecents] = useState<RecentConversation[]>([]);
  const currentUser = useCurrentUser();
  const [loggingOut, setLoggingOut] = useState(false);
  const [accountError, setAccountError] = useState("");
  const [githubStars, setGithubStars] = useState<number | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const sidebarToggleRef = useRef<HTMLButtonElement>(null);
  const sidebarPreviewOpenTimer = useRef<number | null>(null);
  const sidebarPreviewCloseTimer = useRef<number | null>(null);
  const sidebarOpen = sidebarMode !== "collapsed";
  const sidebarPinned = sidebarMode === "pinned";

  useLayoutEffect(() => {
    const saved = window.localStorage.getItem(SIDEBAR_STATE_KEY);
    setSidebarMode(saved === "false" ? "pinned" : "collapsed");
    const frame = window.requestAnimationFrame(() => setSidebarReady(true));
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => () => {
    if (sidebarPreviewOpenTimer.current !== null) window.clearTimeout(sidebarPreviewOpenTimer.current);
    if (sidebarPreviewCloseTimer.current !== null) window.clearTimeout(sidebarPreviewCloseTimer.current);
  }, []);

  useEffect(() => {
    if (settingsMode || resourceMode) return;
    let active = true;
    async function refreshRecents(force = false) {
      try {
        const items = await listRecentConversationsCached({ force });
        if (active) setRecents(items);
      } catch { /* Navigation stays available while history is unavailable. */ }
    }
    void refreshRecents();
    const handleUpdated = () => void refreshRecents(true);
    window.addEventListener("openrealtime:conversations-updated", handleUpdated);
    return () => { active = false; window.removeEventListener("openrealtime:conversations-updated", handleUpdated); };
  }, [resourceMode, settingsMode]);

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/github-stars", { signal: controller.signal })
      .then((response) => response.json())
      .then((data: { stars?: unknown }) => {
        if (!controller.signal.aborted && typeof data.stars === "number") setGithubStars(data.stars);
      }).catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (searchOpen) searchRef.current?.focus();
  }, [searchOpen]);

  useEffect(() => {
    setMobileOpen(false);
    setAccountOpen(false);
    setSidebarMode((current) => transitionSidebarMode(current, "hover-leave"));
  }, [pathname]);

  const filteredRecents = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return needle ? recents.filter((item) => item.title.toLocaleLowerCase().includes(needle)) : recents;
  }, [query, recents]);

  function cancelSidebarPreviewTimers() {
    if (sidebarPreviewOpenTimer.current !== null) window.clearTimeout(sidebarPreviewOpenTimer.current);
    if (sidebarPreviewCloseTimer.current !== null) window.clearTimeout(sidebarPreviewCloseTimer.current);
    sidebarPreviewOpenTimer.current = null;
    sidebarPreviewCloseTimer.current = null;
  }

  function setSidebarPinned(next: boolean) {
    cancelSidebarPreviewTimers();
    setSidebarMode((current) => transitionSidebarMode(current, next ? "pin" : "collapse"));
    window.localStorage.setItem(SIDEBAR_STATE_KEY, String(!next));
    if (!next) {
      setSearchOpen(false);
      setQuery("");
      setAccountOpen(false);
    }
  }

  function keepSidebarOpenOnNavigation(event: MouseEvent<HTMLElement>) {
    if (sidebarMode !== "preview" || !(event.target instanceof Element)) return;
    if (event.target.closest("a")) setSidebarPinned(true);
  }

  function queueSidebarPreview() {
    if (!window.matchMedia("(min-width: 761px)").matches || sidebarPinned) return;
    cancelSidebarPreviewTimers();
    sidebarPreviewOpenTimer.current = window.setTimeout(() => {
      setSidebarMode((current) => transitionSidebarMode(current, "hover-enter"));
      sidebarPreviewOpenTimer.current = null;
    }, 150);
  }

  function keepSidebarPreviewOpen() {
    if (!window.matchMedia("(min-width: 761px)").matches) return;
    cancelSidebarPreviewTimers();
  }

  function scheduleSidebarPreviewClose() {
    if (!window.matchMedia("(min-width: 761px)").matches || sidebarPinned) return;
    if (sidebarPreviewOpenTimer.current !== null) window.clearTimeout(sidebarPreviewOpenTimer.current);
    sidebarPreviewOpenTimer.current = null;
    if (sidebarPreviewCloseTimer.current !== null) window.clearTimeout(sidebarPreviewCloseTimer.current);
    sidebarPreviewCloseTimer.current = window.setTimeout(() => {
      setSidebarMode((current) => transitionSidebarMode(current, "hover-leave"));
      sidebarPreviewCloseTimer.current = null;
    }, 350);
  }

  async function logout() {
    if (loggingOut) return;
    setLoggingOut(true);
    setAccountError("");
    try {
      await logoutCurrentUser();
      window.location.assign("/");
    } catch (cause) {
      setAccountError(cause instanceof Error ? cause.message : "退出登录失败");
      setLoggingOut(false);
    }
  }

  const sectionSidebar = settingsMode || resourceMode;
  const currentResourceTab = resourceTab ?? "avatars";
  const resourceHref = (tab: ResourceNavigationTab) => `/resources?tab=${tab}${resourceReturnTo ? `&return_to=${encodeURIComponent(resourceReturnTo)}` : ""}`;

  const sidebar = sectionSidebar ? <aside
    id="workspace-navigation"
    className={`${styles.sidebar} ${styles.settingsSidebar}`}
    data-mobile-open={mobileOpen}
    data-floating="true"
    data-open={sidebarOpen}
    data-mode={sidebarMode}
    aria-hidden={!sidebarOpen && !mobileOpen}
    inert={!sidebarOpen && !mobileOpen}
    aria-label={settingsMode ? "设置导航" : "资源导航"}
    onClickCapture={keepSidebarOpenOnNavigation}
    onPointerEnter={keepSidebarPreviewOpen}
    onPointerLeave={scheduleSidebarPreviewClose}
  >
    <div className={styles.settingsTop}>
      <Link className={styles.settingsBack} href="/"><ChevronLeft />返回应用</Link>
      <button className={styles.mobileClose} type="button" aria-label="关闭导航" onClick={() => setMobileOpen(false)}><X /></button>
    </div>
    <div className={styles.settingsTitle}>{settingsMode ? "设置" : "资源库"}</div>
    {settingsMode ? <nav className={styles.settingsNav} aria-label="设置选项">
      <NavLink href="/settings" active={pathname === "/settings"} icon={<Settings />} label="总览" />
      <div className={styles.settingsGroupLabel}>账户</div>
      <NavLink href="/settings/profile" active={pathname === "/settings/profile"} icon={<UserRound />} label="个人资料" />
      <NavLink href="/settings/providers" active={pathname === "/settings/providers"} icon={<SlidersHorizontal />} label="供应商" />
      <div className={styles.settingsGroupLabel}>偏好</div>
      <NavLink href="/settings/appearance" active={pathname === "/settings/appearance"} icon={<Palette />} label="外观" />
      <NavLink href="/settings/memory" active={pathname === "/settings/memory"} icon={<MemoryStick />} label="Memory 与隐私" />
      <NavLink href="/settings/advanced" active={pathname === "/settings/advanced"} icon={<Settings2 />} label="高级配置" />
      <div className={styles.settingsGroupLabel}>系统</div>
      <NavLink href="/settings/services" active={pathname === "/settings/services"} icon={<Server />} label="模型服务" />
    </nav> : <nav className={styles.settingsNav} aria-label="资源分类">
      <div className={styles.settingsGroupLabel}>角色素材</div>
      <NavLink href={resourceHref("voices")} active={currentResourceTab === "voices"} icon={<Mic2 />} label="声音" onClick={() => setMobileOpen(false)} />
      <NavLink href={resourceHref("personas")} active={currentResourceTab === "personas"} icon={<Bot />} label="人设" onClick={() => setMobileOpen(false)} />
      <NavLink href={resourceHref("avatars")} active={currentResourceTab === "avatars"} icon={<Sparkles />} label="离线数字人" onClick={() => setMobileOpen(false)} />
      {realtimeConfigured ? <NavLink href={resourceHref("official-realtime")} active={currentResourceTab === "official-realtime"} icon={<UserRound />} label="实时数字人" onClick={() => setMobileOpen(false)} /> : null}
      <div className={styles.settingsGroupLabel}>对话能力</div>
      <NavLink href={resourceHref("tools")} active={currentResourceTab === "tools"} icon={<Wrench />} label="工具" onClick={() => setMobileOpen(false)} />
      <NavLink href={resourceHref("knowledge")} active={currentResourceTab === "knowledge"} icon={<BookOpen />} label="知识库" onClick={() => setMobileOpen(false)} />
    </nav>}
  </aside> : <aside
    id="workspace-navigation"
    className={styles.sidebar}
    data-account-open={accountOpen}
    data-mobile-open={mobileOpen}
    data-floating="true"
    data-open={sidebarOpen}
    data-mode={sidebarMode}
    aria-hidden={!sidebarOpen && !mobileOpen}
    inert={!sidebarOpen && !mobileOpen}
    aria-label="OpenRealtime 导航"
    onClickCapture={keepSidebarOpenOnNavigation}
    onPointerEnter={keepSidebarPreviewOpen}
    onPointerLeave={scheduleSidebarPreviewClose}
  >
    <div className={styles.brandRow}>
      <Link className={styles.brand} href="/" aria-label="OpenRealtime 首页">
        <span className={styles.brandMark}>OR</span>
        <span className={styles.sidebarCopy}>OpenRealtime</span>
      </Link>
      <button className={styles.mobileClose} type="button" aria-label="关闭导航" onClick={() => setMobileOpen(false)}><X /></button>
    </div>

    <nav className={styles.primaryNav} aria-label="主要导航">
      <button className={styles.navRow} type="button" onClick={() => {
        if (sidebarMode === "preview") setSidebarPinned(true);
        // A same-route reset must tear down the active media session; other pages can use fast client navigation.
        if (pathname === "/conversation") window.location.assign("/conversation");
        else router.push("/conversation");
      }}>
        <MessageSquarePlus />
        <span className={styles.sidebarCopy}>新对话</span>
      </button>
      <NavLink href="/roles" active={pathname.startsWith("/roles")} icon={<UsersRound />} label="角色" />
      <NavLink href="/resources" active={isResourceWorkspacePath(pathname)} icon={<LibraryBig />} label="资源" />
      <NavLink href="/docs" active={pathname.startsWith("/docs")} icon={<BookOpen />} label="文档" />
    </nav>

    <section className={styles.recentSection} aria-label="最近对话">
      <div className={styles.recentHeading}>
        <Link className={styles.sidebarCopy} href="/conversations"><History />最近对话</Link>
        <button type="button" aria-label="搜索最近对话" onClick={() => setSearchOpen(true)}><Search /></button>
      </div>
      <div className={styles.searchField} data-open={searchOpen}>
        <Search />
        <input
          ref={searchRef}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setSearchOpen(false);
              setQuery("");
            }
          }}
          placeholder="搜索对话"
          aria-label="搜索最近对话"
        />
        <button type="button" aria-label="关闭搜索" onClick={() => { setSearchOpen(false); setQuery(""); }}><X /></button>
      </div>
      <div className={styles.recentList}>
        {filteredRecents.map((item) => (
          <Link key={item.id} href={`/conversations/${encodeURIComponent(item.id)}`} title={item.title}>
            <span className={styles.sidebarCopy}>{item.title}</span>
          </Link>
        ))}
        {!filteredRecents.length ? <p className={styles.sidebarCopy}>{query ? "没有匹配的对话" : "还没有对话记录"}</p> : null}
      </div>
    </section>

    <a className={styles.githubLink} href="https://github.com/happy-token/OpenRealtime" target="_blank" rel="noopener noreferrer" aria-label="在 GitHub 查看并 Star OpenRealtime"><GitFork aria-hidden="true" /><span className={styles.sidebarCopy}>GitHub</span><Star aria-hidden="true" />{githubStars !== null ? <span>{githubStars.toLocaleString()}</span> : <span className={styles.sidebarCopy}>Star</span>}</a>
    <div className={styles.accountArea}>
      {currentUser.status === "signed-in" ? <><button
        className={styles.accountButton}
        type="button"
        aria-expanded={accountOpen}
        onClick={() => setAccountOpen((open) => !open)}
      >
        <span className={styles.accountAvatar}><UserRound /></span>
        <span className={styles.sidebarCopy}><strong>{currentUser.user.subject}</strong><small>{accountIssuerLabel(currentUser.user.issuer)}</small></span>
        <ChevronDown className={styles.sidebarCopy} />
      </button>
      {accountOpen ? <div className={styles.accountMenu}>
        <Link href="/settings/profile"><UserRound />个人资料</Link>
        <Link href="/settings"><Settings />设置</Link>
        <Link href="/settings/services"><SlidersHorizontal />模型服务</Link>
        <button type="button" disabled={loggingOut} onClick={() => void logout()}><LogOut />{loggingOut ? "正在退出…" : "退出登录"}</button>
        {accountError ? <p className={styles.accountError} role="alert">{accountError}</p> : null}
      </div> : null}</> : <Link className={styles.accountButton} href={accountLoginHref(pathname || "/")}>
        <span className={styles.accountAvatar}><LogIn /></span>
        <span className={styles.sidebarCopy}><strong>登录</strong><small>{currentUser.status === "loading" ? "正在检查账户" : currentUser.status === "unavailable" ? "账户服务暂不可用" : "同步个人配置"}</small></span>
      </Link>}
    </div>
  </aside>;

  return <div className={styles.shell} style={{ "--workspace-sidebar-width": sidebarPinned ? "260px" : "0px" } as CSSProperties} data-settings={settingsMode} data-resources={resourceMode} data-session={session} data-floating-sidebar="true" data-sidebar-open={sidebarOpen} data-sidebar-pinned={sidebarPinned} data-sidebar-mode={sidebarMode} data-sidebar-ready={sidebarReady}>
    <button className={styles.mobileMenu} type="button" aria-label="打开导航" onClick={() => setMobileOpen(true)}><Menu /></button>
    <button
      ref={sidebarToggleRef}
      className={styles.sidebarToggle}
      type="button"
      aria-label={sidebarPinned ? "折叠侧边栏" : "固定展开侧边栏"}
      aria-expanded={sidebarOpen}
      aria-controls="workspace-navigation"
      data-open={sidebarOpen}
      data-pinned={sidebarPinned}
      onClick={() => setSidebarPinned(!sidebarPinned)}
    ><PanelLeft aria-hidden="true" /></button>
    <div
      className={styles.sidebarHoverRail}
      aria-hidden="true"
      data-open={sidebarOpen}
      data-pinned={sidebarPinned}
      data-hover-reveal="true"
      onPointerEnter={queueSidebarPreview}
      onPointerLeave={scheduleSidebarPreviewClose}
    ><span className={styles.sidebarHoverRailLine} /></div>
    {sidebar}
    {mobileOpen ? <button className={styles.mobileBackdrop} type="button" aria-label="关闭导航" onClick={() => setMobileOpen(false)} /> : null}
    <main className={styles.content} data-home-background={!session}>
      {session || immersive ? children : <div className={styles.pageGlass} data-page-glass="true">{children}</div>}
    </main>
  </div>;
}

function NavLink({ href, active, icon, label, onClick }: { href: string; active: boolean; icon: ReactNode; label: string; onClick?: () => void }) {
  return <Link className={styles.navRow} data-active={active} aria-current={active ? "page" : undefined} href={href} onClick={onClick}>
    {icon}<span className={styles.sidebarCopy}>{label}</span>
  </Link>;
}

export function conversationHref(role: RoleRecord, mode: RolePresentationMode, actionId?: string | null, talkingVariantId?: string | null) {
  const params = new URLSearchParams({ role_id: role.role_id, role_mode: mode });
  if (mode === "conversation") params.set("experience", "voice");
  else {
    params.set("experience", "avatar");
    if (role.avatar_id) params.set("avatar_id", role.avatar_id);
    if (mode !== "realtime" && actionId) params.set("avatar_action_id", actionId);
    if (mode === "offline" && talkingVariantId) params.set("talking_variant_id", talkingVariantId);
  }
  return `/conversation?${params.toString()}`;
}
