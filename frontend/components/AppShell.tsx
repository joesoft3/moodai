"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AudioLines, FolderOpen, Image as ImageIcon, LogOut, Menu, MessageSquare, Settings, ShieldCheck } from "lucide-react";
import ConversationList from "./ConversationList";
import { API, apiFetch, token } from "@/lib/api";
import { applyAccent, applyFavicon, BrandMark } from "@/lib/brand";

const NAV = [
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/voice", label: "Voice", icon: AudioLines },
  { href: "/images", label: "Images", icon: ImageIcon },
  { href: "/files", label: "Files", icon: FolderOpen },
  { href: "/settings", label: "Settings", icon: Settings },
] as const;

/**
 * Responsive app shell with a bulletproof mobile bottom bar:
 *  - The bar is in normal flow (never position:fixed) inside an .app-height column
 *  - .app-height is synced from window.visualViewport via JS (--app-h), so on ANY
 *    browser — including old Safari without 100dvh — the layout is exactly the
 *    visible screen height and the bar can't render below the fold
 *  - The nav drawer uses `visibility` (not pointer-events tricks), so a closed
 *    drawer CANNOT intercept taps meant for the tab bar
 *  - touch-action: manipulation on tappables → instant response, no gesture hijack
 */
export default function AppShell({
  title,
  children,
  headerRight,
}: {
  title: string;
  children: React.ReactNode;
  headerRight?: React.ReactNode;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [brand, setBrand] = useState<{
    brand_name: string;
    domain: string;
    accent?: string | null;
    logo_data?: string | null;
  } | null>(null);
  const pathname = usePathname();
  const router = useRouter();
  const rootRef = useRef<HTMLDivElement>(null);

  // Auth guard for every page that uses the shell
  useEffect(() => {
    if (!token.get()) router.push("/login");
  }, [router]);

  // Owner panel entry for admins (server double-checks on every /admin call)
  useEffect(() => {
    if (!token.get()) return;
    apiFetch<{ is_admin?: boolean }>("/auth/me")
      .then((m) => setIsAdmin(Boolean(m.is_admin)))
      .catch(() => {});
  }, []);

  // White-label: reached via an active custom domain? → adopt the owner's brand
  // (name in the sidebar, tab title, accent color, logo + favicon)
  useEffect(() => {
    const host = window.location.host;
    if (/localhost|127\.0\.0\.1/.test(host)) return;
    fetch(`${API}/domains/by-host?host=${encodeURIComponent(host)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => {
        if (b?.brand_name) {
          setBrand(b);
          document.title = `${b.brand_name} — AI assistant`;
          if (b.accent) applyAccent(b.accent);
          if (b.logo_data) applyFavicon(b.logo_data);
        }
      })
      .catch(() => {});
  }, []);

  // Keep --app-h synced to the REAL visible viewport (handles mobile browser
  // chrome show/hide, older Safari without dvh, and the on-screen keyboard)
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const setH = () => {
      const h = window.visualViewport?.height ?? window.innerHeight;
      el.style.setProperty("--app-h", `${Math.round(h)}px`);
    };
    setH();
    window.addEventListener("resize", setH);
    window.visualViewport?.addEventListener("resize", setH);
    window.visualViewport?.addEventListener("scroll", setH);
    return () => {
      window.removeEventListener("resize", setH);
      window.visualViewport?.removeEventListener("resize", setH);
      window.visualViewport?.removeEventListener("scroll", setH);
    };
  }, []);

  function logout() {
    token.clear();
    router.push("/login");
  }

  const sideNav = (
    <div className="flex flex-col h-full">
      <div className="px-5 py-4 flex items-center gap-2 border-b border-line shrink-0">
        <BrandMark brand={brand} />
        <div className="min-w-0">
          <span className="font-bold tracking-tight block truncate">{brand?.brand_name ?? "Mood AI"}</span>
          {brand && <span className="text-[10px] text-gray-500 block -mt-0.5">powered by Mood AI</span>}
        </div>
      </div>
      <ConversationList onNavigate={() => setDrawerOpen(false)} />
      <div className="border-t border-line p-2 space-y-1 shrink-0">
        {NAV.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            onClick={() => setDrawerOpen(false)}
            className={`touch-manipulation flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition ${
              pathname === href ? "bg-accent/15 text-white" : "text-gray-400 hover:bg-white/5"
            }`}
          >
            <Icon size={16} /> {label}
          </Link>
        ))}
        {isAdmin && (
          <Link
            href="/admin"
            onClick={() => setDrawerOpen(false)}
            className={`touch-manipulation flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition ${
              pathname === "/admin" ? "bg-accent/15 text-white" : "text-gray-400 hover:bg-white/5"
            }`}
          >
            <ShieldCheck size={16} /> Owner
          </Link>
        )}
        <button
          onClick={logout}
          className="touch-manipulation w-full flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-gray-500 hover:text-red-400 transition"
        >
          <LogOut size={16} /> Sign out
        </button>
      </div>
    </div>
  );

  return (
    <div ref={rootRef} className="app-height flex overflow-hidden">
      {/* Desktop / landscape-tablet sidebar — widens on large monitors */}
      <aside className="hidden lg:flex w-72 xl:w-80 2xl:w-96 flex-col border-r border-line bg-panel shrink-0">
        {sideNav}
      </aside>

      {/* Slide-over drawer (phone + tablet).
          Uses `visibility`: when closed it is invisible AND cannot receive taps. */}
      <div
        className={`fixed inset-0 z-40 lg:hidden transition-[visibility] duration-200 ${
          drawerOpen ? "visible" : "invisible"
        }`}
      >
        <div
          onClick={() => setDrawerOpen(false)}
          className={`absolute inset-0 h-full bg-black/60 transition-opacity duration-200 ${
            drawerOpen ? "opacity-100" : "opacity-0"
          }`}
        />
        <div
          className={`absolute inset-y-0 left-0 w-72 md:w-80 bg-panel border-r border-line transform transition-transform duration-200 pb-[env(safe-area-inset-bottom)] ${
            drawerOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          {sideNav}
        </div>
      </div>

      {/* Main column: header → scrollable content → in-flow bottom tab bar */}
      <div className="flex-1 min-w-0 flex flex-col min-h-0 relative z-0">
        {/* Header (phone + tablet) */}
        <header className="lg:hidden flex items-center gap-2 border-b border-line px-3 py-3 bg-panel/60 backdrop-blur shrink-0 compact-v pt-[max(0.75rem,env(safe-area-inset-top))]">
          <button
            onClick={() => setDrawerOpen(true)}
            className="touch-manipulation p-2 text-gray-300 hover:text-white"
            aria-label="Open menu"
          >
            <Menu size={20} />
          </button>
          <h1 className="flex-1 text-sm font-semibold truncate">{title}</h1>
          {headerRight}
        </header>

        {/* Page content */}
        <div className="flex-1 min-h-0 flex flex-col">{children}</div>

        {/* Bottom tab bar (phones only) — in flow, raised above content, always tappable */}
        <nav className="md:hidden shrink-0 relative z-10 border-t border-line bg-panel pb-[env(safe-area-inset-bottom)]">
          <div className="grid grid-cols-5 h-14 max-[340px]:h-12">
            {NAV.map(({ href, label, icon: Icon }) => {
              const active = pathname === href;
              return (
                <Link
                  key={href}
                  href={href}
                  className={`touch-manipulation select-none flex flex-col items-center justify-center gap-0.5 text-[10px] transition ${
                    active ? "text-accent" : "text-gray-500 active:text-gray-300"
                  }`}
                >
                  <Icon size={20} />
                  <span className="max-[340px]:hidden">{label}</span>
                </Link>
              );
            })}
          </div>
        </nav>
      </div>
    </div>
  );
}
