"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity, Brain, Copy, CreditCard, Dices, Eye, EyeOff, Globe, KeyRound, LogOut, Puzzle, RefreshCw, SearchCheck, SlidersHorizontal, Trash2, User, Users, X } from "lucide-react";
import { generatePassword, passwordStrength } from "@/lib/password";
import AppShell from "@/components/AppShell";
import { apiFetch, token } from "@/lib/api";
import { copyText } from "@/lib/clipboard";

interface Me {
  id: string;
  email: string;
  display_name: string | null;
  plan: string;
  custom_instructions?: string | null;
}

interface Mem {
  id: string;
  fact: string;
  category?: string;
  title?: string | null; // set for remembered past conversations
}

interface Meter {
  used: number;
  limit: number;
  unlimited: boolean;
  pct: number;
}

interface UsageSummary {
  plan: string;
  tokens_month: Meter;
  images_month: Meter;
  deepsearch_day: Meter;
  agent_day: Meter;
  video_day?: Meter;
  arena_day?: Meter;
  daily_tokens: { date: string; tokens: number }[];
}

interface PluginStatus {
  provider: string;
  name: string;
  icon: string;
  description: string;
  configured: boolean;
  connected: boolean;
  account: string | null;
}

interface Workspace {
  id: string;
  name: string;
  role: string;
  owner: boolean;
  member_count: number;
}

interface WsMember {
  user_id: string;
  email: string | null;
  role: string;
}

interface WsDetail {
  id: string;
  name: string;
  members: WsMember[];
}

interface Seat {
  user_id: string;
  email: string | null;
  plan: string;
  requests_month: number;
  tokens_month: number;
}

interface DomainProviders {
  registrar: boolean;
  registrar_env: string;
  stripe: boolean;
  platform_cname: string;
  markup_pct: number;
}

interface DomainRec {
  id: string;
  domain: string;
  kind: string;
  status: string;
  brand_name: string | null;
  years: number;
  price_cents: number;
  currency: string;
  auto_renew: boolean;
  workspace_id: string | null;
  expires_at: string | null;
  accent: string | null;
  has_logo: boolean;
  dns?: { txt_name: string; txt_value: string; cname_target: string } | null;
  arena?: DomainArena;
}

/** ⚔️ White-label arena settings returned per domain (owner view). */
interface DomainArena {
  enabled: boolean;
  daily_cap: number; // 0 = inherit the visitor's plan cap
  brand: string | null;
  judge: string | null;
  panel: { provider: string; model: string; label: string }[];
}

const ARENA_JUDGES = ["", "grok-4", "grok-4-fast", "grok-3-mini", "grok-code-fast-1"];
const ARENA_PROVIDERS = ["xai", "openai", "gemini"] as const;

interface DomainStats {
  days: { day: string; requests: number; users: number }[];
  today: { day: string; requests: number; users: number };
  total_requests: number;
  peak_daily_users: number;
}

interface InviteRec {
  id: string;
  token: string;
  expires_at: string | null;
  revoked: boolean;
}

interface DomainResult {
  domain: string;
  available: boolean;
  cost_cents: number;
  price_cents: number | null;
  currency: string;
}

const EMPTY_CONTACT = {
  name_first: "", name_last: "", email: "", phone: "",
  address1: "", city: "", state: "", postal_code: "", country: "",
};

function money(cents: number, currency: string) {
  return `${(cents / 100).toFixed(2)} ${currency}`;
}

function CopyBtn({ text }: { text: string }) {
  const [state, setState] = useState<"" | "ok" | "fail">("");
  return (
    <button
      onClick={async () => {
        setState((await copyText(text)) ? "ok" : "fail");
        setTimeout(() => setState(""), 1200);
      }}
      className="text-gray-500 hover:text-gray-200 transition shrink-0"
      title={state === "fail" ? "Copy blocked by browser" : "Copy"}
    >
      {state === "ok" ? <span className="text-[10px] text-green-400">✓</span>
        : state === "fail" ? <span className="text-[10px] text-red-400">✗</span>
        : <Copy size={12} />}
    </button>
  );
}

function fmt(n: number): string {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`;
}

/** Registrar renewal/expiry badge for purchased domains. */
function expiryLabel(d: DomainRec): { text: string; cls: string } | null {
  if (d.kind !== "purchased") return null;
  if (!d.expires_at) return { text: "expiry syncing…", cls: "text-gray-600" };
  const days = Math.ceil((new Date(d.expires_at).getTime() - Date.now()) / 86400000);
  if (days < 0) return { text: "⚠ expired", cls: "text-red-400" };
  if (days <= 30) return { text: `⚠ expires in ${days}d`, cls: "text-yellow-500" };
  return { text: `renews ${d.expires_at.slice(0, 10)}`, cls: "text-gray-500" };
}

const ACCENT_PRESETS = ["#7c9bff", "#22c55e", "#f59e0b", "#ef4444", "#a855f7", "#06b6d4", "#ec4899"];

function ExpiryPill({ d }: { d: DomainRec }) {
  const b = expiryLabel(d);
  if (!b) return null;
  return <span className={b.cls}>{b.text}</span>;
}

/** Renewal checkout makes sense inside the last 30 days before expiry. */
function renewDue(d: DomainRec): boolean {
  if (d.kind !== "purchased" || d.status !== "active" || !d.expires_at) return false;
  return new Date(d.expires_at).getTime() - Date.now() <= 30 * 86400000;
}

function MeterBar({ label, m, period }: { label: string; m: Meter; period: string }) {
  const hard = !m.unlimited && m.pct >= 90;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-gray-400">{label}</span>
        <span className="text-gray-500">
          {fmt(m.used)}
          {m.unlimited ? " · unlimited" : ` / ${fmt(m.limit)} ${period}`}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-base overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${hard ? "bg-red-400" : "bg-accent"}`}
          style={{ width: `${m.unlimited ? Math.min(m.pct, 100) : Math.max(m.pct, 2)}%` }}
        />
      </div>
    </div>
  );
}

function Card({
  icon,
  title,
  action,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-panel border border-line rounded-2xl p-5 space-y-4">
      <header className="flex items-center gap-2 text-sm font-semibold">
        <span className="text-accent">{icon}</span> {title}
        {action && <span className="ml-auto">{action}</span>}
      </header>
      {children}
    </section>
  );
}

/** Download a Blob response as a file (CSV exports). */
function saveBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 8000);
}

export default function SettingsPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [mems, setMems] = useState<Mem[] | null>(null);
  const [memError, setMemError] = useState("");
  const [billing, setBilling] = useState<{ status: string; period?: string | null } | null>(null);
  const [billingMsg, setBillingMsg] = useState("");
  const [instructions, setInstructions] = useState("");
  const [instrSaved, setInstrSaved] = useState(false);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [plugins, setPlugins] = useState<PluginStatus[] | null>(null);
  const [pluginMsg, setPluginMsg] = useState("");
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null);
  const [wsDetail, setWsDetail] = useState<WsDetail | null>(null);
  const [wsSeats, setWsSeats] = useState<Seat[] | null>(null);
  const [wsName, setWsName] = useState("");
  const [wsInvite, setWsInvite] = useState("");
  const [wsMsg, setWsMsg] = useState("");
  // ---- domains
  const [domProviders, setDomProviders] = useState<DomainProviders | null>(null);
  const [domains, setDomains] = useState<DomainRec[] | null>(null);
  const [domTab, setDomTab] = useState<"connect" | "buy">("connect");
  const [domMsg, setDomMsg] = useState("");
  const [connectForm, setConnectForm] = useState({ domain: "", brand: "" });
  const [domBusy, setDomBusy] = useState(false);
  // ☠️ danger zone
  const [confirmDel, setConfirmDel] = useState(false);
  const [delPw, setDelPw] = useState("");
  const [delBusy, setDelBusy] = useState(false);
  const [delMsg, setDelMsg] = useState("");
  // 🔑 security — change password (v1.8.0)
  const [pwCur, setPwCur] = useState("");
  const [pwNew, setPwNew] = useState("");
  const [pwShow, setPwShow] = useState(false);
  const [pwBusy, setPwBusy] = useState(false);
  const [pwCopied, setPwCopied] = useState(false);
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [buyQuery, setBuyQuery] = useState("");
  const [buyResults, setBuyResults] = useState<DomainResult[] | null>(null);
  const [buyPick, setBuyPick] = useState<DomainResult | null>(null);
  const [buyYears, setBuyYears] = useState(1);
  const [buyContact, setBuyContact] = useState({ ...EMPTY_CONTACT });
  const [buyBrand, setBuyBrand] = useState("");
  // ---- domains: manage (theme/gate), analytics, renewals
  const [domOpen, setDomOpen] = useState<string | null>(null);
  const [domEdit, setDomEdit] = useState<{
    brand: string;
    accent: string;
    logo: string | null;
    workspace: string;
    arenaOn: boolean;
    arenaCap: string; // "" = inherit plan cap
    arenaBrand: string;
    arenaJudge: string;
    arenaPanel: { provider: string; model: string; label: string }[];
  } | null>(null);
  const [domStatsOpen, setDomStatsOpen] = useState<string | null>(null);
  const [domStats, setDomStats] = useState<Record<string, DomainStats>>({});
  // ---- teams: invite links
  const [wsInvites, setWsInvites] = useState<InviteRec[] | null>(null);
  const [wsEmails, setWsEmails] = useState("");

  useEffect(() => {
    // OAuth callback lands here as /settings?plugin=connected|error (no Suspense needed)
    const q = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("plugin") : null;
    if (q === "connected") setPluginMsg("✅ App connected — Mood can now act on it in chat (🧩 toggle).");
    if (q === "error") setPluginMsg("⚠️ Connection failed — please try again.");
    if (q) window.history.replaceState({}, "", window.location.pathname);
    apiFetch<Me>("/auth/me")
      .then((m) => {
        setMe(m);
        setInstructions(m.custom_instructions ?? "");
      })
      .catch(() => {});
    apiFetch<any>("/billing/status")
      .then((s) => setBilling({ status: s.subscription ?? "none", period: s.current_period_end }))
      .catch(() => setBilling(null));
    loadMemories();
    apiFetch<UsageSummary>("/usage/summary").then(setUsage).catch(() => setUsage(null));
    loadPlugins();
    loadWorkspaces();
    loadDomains();
    apiFetch<DomainProviders>("/domains/providers").then(setDomProviders).catch(() => {});
    const dp = new URLSearchParams(window.location.search).get("domain_purchase");
    if (dp === "success") setDomMsg("✅ Payment received — your domain is being registered & connected (this takes ~30s).");
    if (dp === "cancelled") setDomMsg("Purchase cancelled — nothing was charged.");
    if (dp) window.history.replaceState({}, "", window.location.pathname);
    const dr = new URLSearchParams(window.location.search).get("domain_renewal");
    if (dr === "success") setDomMsg("✅ Payment received — your registration is being extended at the registrar. Hit Sync in a minute.");
    if (dr === "cancelled") setDomMsg("Renewal cancelled — nothing was charged.");
    if (dr) window.history.replaceState({}, "", window.location.pathname);
  }, []);

  async function loadDomains() {
    try {
      const j = await apiFetch<{ domains: DomainRec[] }>("/domains");
      setDomains(j.domains);
    } catch {
      setDomains(null);
    }
  }

  async function connectDomain() {
    if (!connectForm.domain.trim() || domBusy) return;
    setDomBusy(true);
    setDomMsg("");
    try {
      await apiFetch("/domains/connect", {
        method: "POST",
        body: JSON.stringify({ domain: connectForm.domain.trim(), brand_name: connectForm.brand.trim() || null }),
      });
      setConnectForm({ domain: "", brand: "" });
      await loadDomains();
      setDomMsg("✅ Domain added — finish the DNS setup below, then hit Verify.");
    } catch (e: any) {
      setDomMsg("⚠️ " + (e.message ?? "Connect failed"));
    } finally {
      setDomBusy(false);
    }
  }

  async function verifyDomain(id: string) {
    setDomMsg("");
    try {
      const d = await apiFetch<DomainRec>(`/domains/${id}/verify`, { method: "POST" });
      if (d.status === "active") setDomMsg(`✅ ${d.domain} is live! HTTPS is issued automatically when traffic arrives.`);
      else setDomMsg("⏳ DNS not detected yet — propagation can take a few minutes. Try Verify again shortly.");
      await loadDomains();
    } catch (e: any) {
      setDomMsg("⚠️ " + (e.message ?? "Verify failed"));
    }
  }

  async function deleteDomain(id: string) {
    if (!confirm("Remove this domain? Its configuration will be deleted.")) return;
    await apiFetch(`/domains/${id}`, { method: "DELETE" }).catch(() => {});
    await loadDomains();
  }

  // ---- domain manage: brand / accent / logo / team gate
  function toggleManage(d: DomainRec) {
    if (domOpen === d.id) {
      setDomOpen(null);
      setDomEdit(null);
      return;
    }
    setDomOpen(d.id);
    setDomEdit({
      brand: d.brand_name ?? "",
      accent: d.accent ?? "#7c9bff",
      logo: null,
      workspace: d.workspace_id ?? "",
      arenaOn: d.arena?.enabled ?? false,
      arenaCap: d.arena?.daily_cap ? String(d.arena.daily_cap) : "",
      arenaBrand: d.arena?.brand ?? "",
      arenaJudge: d.arena?.judge ?? "",
      arenaPanel: (d.arena?.panel ?? []).map((p) => ({ ...p })),
    });
  }

  async function saveDomain(id: string) {
    if (!domEdit) return;
    setDomMsg("");
    try {
      await apiFetch(`/domains/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          brand_name: domEdit.brand,
          accent: domEdit.accent,
          logo_data: domEdit.logo, // null = unchanged · "" = remove · data URL = set
          workspace_id: domEdit.workspace, // "" = no team gate
          arena_enabled: domEdit.arenaOn,
          arena_daily_cap: domEdit.arenaCap.trim() ? Math.max(0, parseInt(domEdit.arenaCap, 10) || 0) : 0,
          arena_brand: domEdit.arenaBrand, // "" clears
          arena_judge: domEdit.arenaJudge, // "" = platform judge
          arena_panel: domEdit.arenaOn && domEdit.arenaPanel.length ? domEdit.arenaPanel : [],
        }),
      });
      setDomOpen(null);
      setDomEdit(null);
      await loadDomains();
      setDomMsg("✅ Saved — visits on your domain pick up the new branding instantly.");
    } catch (e: any) {
      setDomMsg("⚠️ " + (e.message ?? "Save failed"));
    }
  }

  async function toggleRenew(d: DomainRec) {
    setDomMsg("");
    try {
      await apiFetch(`/domains/${d.id}`, { method: "PATCH", body: JSON.stringify({ auto_renew: !d.auto_renew }) });
      await loadDomains();
      setDomMsg(d.auto_renew ? "Auto-renew turned off at the registrar." : "✅ Auto-renew enabled at the registrar.");
    } catch (e: any) {
      setDomMsg("⚠️ " + (e.message ?? "Toggle failed"));
    }
  }

  /** CSV export state: "usage" or a domain id. */
  const [csvBusy, setCsvBusy] = useState<string | null>(null);

  async function downloadUsageCsv() {
    if (csvBusy) return;
    setCsvBusy("usage");
    try {
      const blob = await apiFetch<Blob>("/usage/export?days=30");
      const since = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
      saveBlob(blob, `mood-usage-${since}.csv`);
    } catch (e: any) {
      alert(e.message ?? "Export failed");
    } finally {
      setCsvBusy(null);
    }
  }

  async function downloadDomainCsv(d: DomainRec) {
    if (csvBusy) return;
    setCsvBusy(d.id);
    try {
      const blob = await apiFetch<Blob>(`/domains/${d.id}/analytics?format=csv`);
      saveBlob(blob, `mood-domain-${d.domain}-14d.csv`);
    } catch (e: any) {
      alert(e.message ?? "Export failed");
    } finally {
      setCsvBusy(null);
    }
  }

  async function refreshDomain(id: string) {
    setDomMsg("");
    try {
      await apiFetch(`/domains/${id}/refresh`, { method: "POST" });
      await loadDomains();
      setDomMsg("✅ Synced expiry & renewal state with the registrar.");
    } catch (e: any) {
      setDomMsg("⚠️ " + (e.message ?? "Refresh failed"));
    }
  }

  async function renewDomain(d: DomainRec) {
    setDomMsg("");
    setDomBusy(true);
    try {
      const j = await apiFetch<{ checkout_url: string }>(`/domains/${d.id}/renew`, {
        method: "POST",
        body: JSON.stringify({ years: 1 }),
      });
      window.location.href = j.checkout_url; // registrar renewal runs after payment (webhook)
    } catch (e: any) {
      setDomMsg("⚠️ " + (e.message ?? "Renewal failed"));
      setDomBusy(false);
    }
  }

  async function toggleStats(d: DomainRec) {
    if (domStatsOpen === d.id) {
      setDomStatsOpen(null);
      return;
    }
    setDomStatsOpen(d.id);
    try {
      const j = await apiFetch<DomainStats>(`/domains/${d.id}/analytics`);
      setDomStats((s) => ({ ...s, [d.id]: j }));
    } catch {
      /* panel shows zeros on failure */
    }
  }

  function pickLogo(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (f.size > 150_000) {
      setDomMsg("⚠️ Logo must be under 150 KB (use a small PNG/WebP).");
      return;
    }
    const rd = new FileReader();
    rd.onload = () => setDomEdit((v) => (v ? { ...v, logo: String(rd.result) } : v));
    rd.readAsDataURL(f);
  }

  async function searchDomains() {
    if (buyQuery.trim().length < 2 || domBusy) return;
    setDomBusy(true);
    setDomMsg("");
    setBuyResults(null);
    setBuyPick(null);
    try {
      const j = await apiFetch<{ results: DomainResult[]; env: string }>(`/domains/search?q=${encodeURIComponent(buyQuery.trim())}`);
      setBuyResults(j.results);
      if (j.results.length === 0) setDomMsg("No results — try another name.");
    } catch (e: any) {
      setDomMsg("⚠️ " + (e.message ?? "Search failed"));
    } finally {
      setDomBusy(false);
    }
  }

  async function buyDomain() {
    if (!buyPick) return;
    const c = buyContact;
    if (!c.name_first || !c.name_last || !c.email || !c.phone || !c.address1 || !c.city || !c.state || !c.postal_code || c.country.length !== 2) {
      setDomMsg("⚠️ Fill in all registrant contact fields (country = 2-letter code, e.g. US or GH).");
      return;
    }
    setDomBusy(true);
    setDomMsg("");
    try {
      const j = await apiFetch<{ checkout_url: string; env: string }>("/domains/purchase", {
        method: "POST",
        body: JSON.stringify({
          domain: buyPick.domain,
          years: buyYears,
          contact: c,
          brand_name: buyBrand.trim() || null,
        }),
      });
      window.location.href = j.checkout_url;
    } catch (e: any) {
      setDomMsg("⚠️ " + (e.message ?? "Purchase failed"));
      setDomBusy(false);
    }
  }

  async function loadWorkspaces() {
    try {
      const j = await apiFetch<{ workspaces: Workspace[] }>("/workspaces");
      setWorkspaces(j.workspaces);
    } catch {
      setWorkspaces(null);
    }
  }

  async function createWorkspace() {
    const name = wsName.trim();
    if (name.length < 2) return;
    setWsMsg("");
    try {
      await apiFetch("/workspaces", { method: "POST", body: JSON.stringify({ name }) });
      setWsName("");
      await loadWorkspaces();
    } catch (e: any) {
      setWsMsg("⚠️ " + (e.message ?? "Create failed"));
    }
  }

  async function openWorkspace(id: string) {
    setWsMsg("");
    try {
      const me = await apiFetch<Me>("/auth/me");
      const d = await apiFetch<WsDetail & { owner_id: string }>(`/workspaces/${id}`);
      setWsDetail(d);
      setWsSeats(null);
      setWsInvites(null);
      if (d.members.some((m) => m.role === "owner" && m.user_id === (me as any).id)) {
        apiFetch<{ seats: Seat[] }>(`/workspaces/${id}/usage`).then((j) => setWsSeats(j.seats)).catch(() => {});
        loadInvites(id);
      }
    } catch (e: any) {
      setWsMsg("⚠️ " + (e.message ?? "Load failed"));
    }
  }

  async function inviteMember() {
    if (!wsDetail || !wsInvite.trim()) return;
    setWsMsg("");
    try {
      await apiFetch(`/workspaces/${wsDetail.id}/members`, {
        method: "POST",
        body: JSON.stringify({ email: wsInvite.trim() }),
      });
      setWsInvite("");
      setWsMsg("✅ Member added — they can open Team chat and see shared conversations.");
      await openWorkspace(wsDetail.id);
      await loadWorkspaces();
    } catch (e: any) {
      setWsMsg("⚠️ " + (e.message ?? "Invite failed"));
    }
  }

  async function removeMember(userId: string) {
    if (!wsDetail || !confirm("Remove this member from the workspace?")) return;
    await apiFetch(`/workspaces/${wsDetail.id}/members/${userId}`, { method: "DELETE" }).catch(() => {});
    await openWorkspace(wsDetail.id);
    await loadWorkspaces();
  }

  // ---- teams: invite links
  async function loadInvites(wid: string) {
    try {
      const j = await apiFetch<{ invites: InviteRec[] }>(`/workspaces/${wid}/invites`);
      setWsInvites(j.invites);
    } catch {
      setWsInvites(null);
    }
  }

  async function createInvite() {
    if (!wsDetail) return;
    setWsMsg("");
    try {
      await apiFetch(`/workspaces/${wsDetail.id}/invites`, { method: "POST" });
      await loadInvites(wsDetail.id);
      setWsMsg("✅ Invite link created — share it with your teammate.");
    } catch (e: any) {
      setWsMsg("⚠️ " + (e.message ?? "Invite failed"));
    }
  }

  async function revokeInvite(iid: string) {
    if (!wsDetail) return;
    await apiFetch(`/workspaces/${wsDetail.id}/invites/${iid}`, { method: "DELETE" }).catch(() => {});
    await loadInvites(wsDetail.id);
  }

  async function emailInvites() {
    if (!wsDetail) return;
    const emails = wsEmails.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean);
    if (!emails.length) return;
    setWsMsg("");
    try {
      const j = await apiFetch<{ sent: number; failed: string[]; link: string }>(
        `/workspaces/${wsDetail.id}/invites/email`,
        { method: "POST", body: JSON.stringify({ emails }) }
      );
      setWsEmails("");
      setWsMsg(
        j.failed.length
          ? `⚠️ Sent ${j.sent}, failed for: ${j.failed.join(", ")} — copy the link below as a fallback.`
          : `✅ Invite emailed to ${j.sent} teammate(s) via your Gmail.`
      );
      await loadInvites(wsDetail.id);
    } catch (e: any) {
      setWsMsg("⚠️ " + (e.message ?? "Email failed"));
    }
  }

  async function loadPlugins() {
    try {
      const j = await apiFetch<{ plugins: PluginStatus[] }>("/plugins");
      setPlugins(j.plugins);
    } catch {
      setPlugins(null);
    }
  }

  async function connectPlugin(provider: string) {
    setPluginMsg("");
    try {
      const j = await apiFetch<{ authorize_url: string }>(`/plugins/${provider}/connect`);
      window.location.href = j.authorize_url; // leave app for OAuth consent, returns to /settings
    } catch (e: any) {
      setPluginMsg("⚠️ " + (e.message ?? "Connect failed"));
    }
  }

  async function disconnectPlugin(provider: string) {
    if (!confirm("Disconnect this app? Mood will lose access immediately.")) return;
    setPlugins((p) => (p ? p.map((x) => (x.provider === provider ? { ...x, connected: false, account: null } : x)) : p));
    await apiFetch(`/plugins/${provider}`, { method: "DELETE" }).catch(loadPlugins);
  }

  async function loadMemories() {
    try {
      const j = await apiFetch<{ memories: Mem[] }>("/memory");
      setMems(j.memories);
      setMemError("");
    } catch (e: any) {
      setMems(null);
      setMemError(e.message ?? "Memory store unavailable");
    }
  }

  async function deleteMem(id: string) {
    setMems((m) => (m ? m.filter((x) => x.id !== id) : m));
    await apiFetch(`/memory/${id}`, { method: "DELETE" }).catch(loadMemories);
  }

  async function clearAll() {
    if (!confirm("Delete ALL of Mood’s memories about you?")) return;
    await apiFetch("/memory", { method: "DELETE" }).catch(() => {});
    loadMemories();
  }

  async function upgrade() {
    setBillingMsg("");
    try {
      const r = await apiFetch<{ checkout_url: string }>("/billing/checkout", { method: "POST" });
      window.location.href = r.checkout_url;
    } catch (e: any) {
      setBillingMsg(e.message ?? "Billing unavailable");
    }
  }

  function logout() {
    token.clear();
    router.push("/login");
  }

  // 🔑 change password — server requires the CURRENT password, refuses no-ops
  async function changePassword() {
    setPwMsg(null);
    if (!pwCur) return setPwMsg({ ok: false, text: "Enter your current password first." });
    if (pwNew.length < 8) return setPwMsg({ ok: false, text: "New password needs at least 8 characters." });
    if (pwCur === pwNew) return setPwMsg({ ok: false, text: "New password must differ from the current one." });
    setPwBusy(true);
    try {
      await apiFetch("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: pwCur, new_password: pwNew }),
      });
      setPwMsg({ ok: true, text: "Password updated ✓ — this device stays signed in." });
      setPwCur(""); setPwNew("");
    } catch (e: any) {
      setPwMsg({ ok: false, text: e?.message || "Couldn't update the password." });
    } finally {
      setPwBusy(false);
    }
  }

  // 🎲 generate + auto-copy a strong password into the new-password field
  async function genNewPassword() {
    const pw = generatePassword(16);
    setPwNew(pw);
    setPwShow(true); // reveal so the owner can read/save it
    setPwMsg(null);
    const ok = await copyText(pw);
    setPwCopied(ok);
    if (ok) setTimeout(() => setPwCopied(false), 2000);
  }

  async function deleteAccount() {
    if (delBusy || !delPw) return;
    setDelBusy(true);
    setDelMsg("");
    try {
      await apiFetch("/auth/me", { method: "DELETE", body: JSON.stringify({ password: delPw }) });
      token.clear();
      router.push("/login?deleted=1");
    } catch (e: any) {
      setDelMsg(e.message ?? "Deletion failed — account kept");
      setDelBusy(false);
    }
  }

  async function saveInstructions() {
    setInstrSaved(false);
    try {
      await apiFetch("/auth/preferences", {
        method: "PATCH",
        body: JSON.stringify({ custom_instructions: instructions.trim() || null }),
      });
      setInstrSaved(true);
      setTimeout(() => setInstrSaved(false), 2000);
    } catch (e: any) {
      alert(e.message ?? "Save failed");
    }
  }

  return (
    <AppShell title="Settings">
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin px-3 sm:px-4 py-6 compact-v">
        <div className="max-w-4xl 2xl:max-w-6xl mx-auto grid gap-4 md:grid-cols-2">
          {/* Account */}
          <Card icon={<User size={16} />} title="Account">
            {me ? (
              <div className="space-y-2 text-sm">
                <p className="text-gray-300">{me.display_name || "Mood user"}</p>
                <p className="text-gray-500 break-all">{me.email}</p>
                <span className="inline-block text-xs rounded-full bg-accent/15 border border-accent/30 text-accent px-2.5 py-1 uppercase tracking-wide">
                  {me.plan} plan
                </span>
              </div>
            ) : (
              <p className="text-sm text-gray-600">Loading…</p>
            )}
            <button onClick={logout} className="flex items-center gap-2 text-sm text-gray-500 hover:text-red-400 transition">
              <LogOut size={14} /> Sign out
            </button>
          </Card>

          {/* Security — password (v1.8.0) */}
          <Card icon={<KeyRound size={16} />} title="Security — password">
            <div className="space-y-3">
              <label className="block">
                <span className="text-xs text-gray-500 block mb-1">Current password</span>
                <input
                  type="password"
                  value={pwCur}
                  onChange={(e) => { setPwCur(e.target.value); setPwMsg(null); }}
                  autoComplete="current-password"
                  className="w-full bg-bg border border-line rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent"
                  placeholder="••••••••"
                />
              </label>
              <label className="block">
                <span className="text-xs text-gray-500 block mb-1">New password</span>
                <div className="relative">
                  <input
                    type={pwShow ? "text" : "password"}
                    value={pwNew}
                    onChange={(e) => { setPwNew(e.target.value); setPwMsg(null); }}
                    autoComplete="new-password"
                    className="w-full bg-bg border border-line rounded-lg px-3 py-2 pr-20 text-sm focus:outline-none focus:border-accent"
                    placeholder="Min 8 characters"
                  />
                  <button
                    type="button"
                    onClick={() => setPwShow((s) => !s)}
                    aria-label={pwShow ? "Hide password" : "Show password"}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-200 p-1"
                  >
                    {pwShow ? <EyeOff size={15} /> : <Eye size={15} />}
                  </button>
                </div>
              </label>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={genNewPassword}
                  className="flex items-center gap-1.5 text-xs rounded-lg border border-line px-2.5 py-1.5 text-gray-300 hover:border-accent hover:text-accent transition"
                >
                  <Dices size={13} /> {pwCopied ? "Copied ✓" : "Generate strong"}
                </button>
                {pwNew && (
                  <span className={`text-[11px] ${passwordStrength(pwNew).cls}`}>
                    {passwordStrength(pwNew).label}
                  </span>
                )}
              </div>
              {pwMsg && (
                <p className={`text-xs ${pwMsg.ok ? "text-emerald-400" : "text-red-400"}`}>{pwMsg.text}</p>
              )}
              <button
                onClick={changePassword}
                disabled={pwBusy || !pwCur || pwNew.length < 8}
                className="rounded-xl bg-accent text-black font-semibold px-4 py-2 text-sm disabled:opacity-40 hover:brightness-110 transition"
              >
                {pwBusy ? "Updating…" : "Change password"}
              </button>
            </div>
          </Card>

          {/* Billing */}
          <Card icon={<CreditCard size={16} />} title="Subscription">

            <p className="text-sm text-gray-400">
              Status: <span className="text-gray-200 font-medium">{billing?.status ?? "unavailable"}</span>
            </p>
            <ul className="text-xs text-gray-400 space-y-1 leading-relaxed">
              <li>⚔️ Arena — <span className="text-gray-200">100 debates/day</span> (free: 3)</li>
              <li>🔢 5M tokens/mo · 🔭 200 deep searches/day · 🎬 60 videos/day</li>
              <li>📎 50 MB uploads (vs 25) · 🧠 365-day memory (vs 30)</li>
              <li>⏫ 4× rate-limit throughput</li>
            </ul>
            <button
              onClick={upgrade}
              className="rounded-xl bg-accent text-black text-sm font-semibold px-4 py-2 hover:brightness-110 transition"
            >
              Upgrade to Pro
            </button>
            {billingMsg && <p className="text-xs text-yellow-500">{billingMsg}</p>}
          </Card>

          {/* Usage */}
          <Card
            icon={<Activity size={16} />}
            title={`Usage · ${usage?.plan ?? "…"} plan`}
            action={
              <button
                onClick={downloadUsageCsv}
                disabled={csvBusy === "usage"}
                title="Download your usage events as a CSV (last 30 days)"
                className="rounded-lg bg-white/5 border border-line px-2.5 py-1 text-[11px] text-gray-300 hover:bg-white/10 transition disabled:opacity-40 flex items-center gap-1"
              >
                {csvBusy === "usage" ? <RefreshCw size={11} className="animate-spin" /> : "⤓"} CSV
              </button>
            }
          >
            {usage ? (
              <>
                <MeterBar label="Tokens this month" m={usage.tokens_month} period="/ mo" />
                <MeterBar label="Images this month" m={usage.images_month} period="/ mo" />
                <MeterBar label="Deep searches today" m={usage.deepsearch_day} period="/ day" />
                <MeterBar label="Agent runs today" m={usage.agent_day} period="/ day" />
                {usage.video_day && <MeterBar label="Videos today" m={usage.video_day} period="/ day" />}
                {usage.arena_day && <MeterBar label="⚔️ Arena debates today" m={usage.arena_day} period="/ day" />}
                <div className="pt-1">
                  <p className="text-[11px] text-gray-500 mb-1.5">Tokens · last 14 days</p>
                  <div className="flex items-end gap-[3px] h-14">
                    {usage.daily_tokens.map((d) => {
                      const max = Math.max(...usage.daily_tokens.map((x) => x.tokens), 1);
                      return (
                        <div
                          key={d.date}
                          title={`${d.date}: ${fmt(d.tokens)} tokens`}
                          className="flex-1 rounded-sm bg-accent/70 hover:bg-accent transition"
                          style={{ height: `${Math.max((d.tokens / max) * 100, 3)}%` }}
                        />
                      );
                    })}
                  </div>
                </div>
              </>
            ) : (
              <p className="text-sm text-gray-600">Usage data unavailable.</p>
            )}
          </Card>

          {/* Plugins */}
          <Card icon={<Puzzle size={16} />} title="Connected apps">
            <p className="text-xs text-gray-500">
              Let Mood read &amp; act in your apps. In chat, turn on the 🧩 toggle and ask —
              e.g. <i>“Check my unread emails”</i> or <i>“Create a GitHub issue for the login bug.”</i>
            </p>
            {pluginMsg && <p className="text-xs text-yellow-500">{pluginMsg}</p>}
            {!plugins && <p className="text-sm text-gray-600">Loading…</p>}
            {plugins && (
              <ul className="space-y-2">
                {plugins.map((p) => (
                  <li key={p.provider} className="flex items-center gap-3 rounded-xl bg-base border border-line px-3 py-2.5">
                    <span className="text-lg shrink-0">{p.icon}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-200 font-medium">{p.name}</p>
                      <p className="text-[11px] text-gray-500 truncate">
                        {p.connected ? `Connected as ${p.account ?? "account"}` : p.description}
                      </p>
                    </div>
                    {p.connected ? (
                      <button
                        onClick={() => disconnectPlugin(p.provider)}
                        className="text-xs rounded-lg bg-red-400/10 border border-red-400/30 px-3 py-1.5 text-red-400 hover:bg-red-400/20 transition shrink-0"
                      >
                        Disconnect
                      </button>
                    ) : (
                      <button
                        onClick={() => connectPlugin(p.provider)}
                        disabled={!p.configured}
                        title={p.configured ? "Connect with OAuth" : "OAuth client not configured on the server"}
                        className="text-xs rounded-lg bg-accent text-black font-semibold px-3 py-1.5 hover:brightness-110 transition shrink-0 disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        {p.configured ? "Connect" : "Setup needed"}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* Teams / workspaces */}
          <div className="md:col-span-2">
            <Card icon={<Users size={16} />} title="Teams — shared workspaces">
              <p className="text-xs text-gray-500">
                Create a workspace, add teammates, and chat together — conversations in a workspace
                are shared with all members (each message shows its author). Owners see per-seat usage.
              </p>
              <div className="flex gap-2">
                <input
                  value={wsName}
                  onChange={(e) => setWsName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") createWorkspace();
                  }}
                  placeholder="New workspace name (e.g. Acme Research)…"
                  className="flex-1 rounded-xl bg-base border border-line px-3 py-2 text-sm outline-none focus:border-accent/60 placeholder-gray-600"
                />
                <button
                  onClick={createWorkspace}
                  disabled={wsName.trim().length < 2}
                  className="rounded-xl bg-accent text-black text-sm font-semibold px-4 py-2 disabled:opacity-30 hover:brightness-110 transition shrink-0"
                >
                  Create
                </button>
              </div>
              {wsMsg && <p className="text-xs text-yellow-500">{wsMsg}</p>}
              {!workspaces || workspaces.length === 0 ? (
                <p className="text-sm text-gray-600">No workspaces yet.</p>
              ) : (
                <ul className="space-y-2">
                  {workspaces.map((w) => (
                    <li key={w.id} className="rounded-xl bg-base border border-line">
                      <div className="flex items-center gap-3 px-3 py-2.5">
                        <span className="text-lg shrink-0">👥</span>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-gray-200 font-medium truncate">{w.name}</p>
                          <p className="text-[11px] text-gray-500">
                            {w.member_count} member{w.member_count === 1 ? "" : "s"} · {w.owner ? "you own it" : "member"}
                          </p>
                        </div>
                        <a
                          href={`/chat?ws=${w.id}`}
                          className="text-xs rounded-lg bg-accent text-black font-semibold px-3 py-1.5 hover:brightness-110 transition shrink-0"
                        >
                          Team chat →
                        </a>
                        <button
                          onClick={() => openWorkspace(w.id)}
                          className="text-xs rounded-lg bg-white/5 border border-line px-3 py-1.5 text-gray-300 hover:bg-white/10 transition shrink-0"
                        >
                          Manage
                        </button>
                      </div>
                      {wsDetail?.id === w.id && (
                        <div className="border-t border-line px-3 py-3 space-y-3">
                          <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Members</p>
                          <ul className="space-y-1.5">
                            {wsDetail.members.map((m) => (
                              <li key={m.user_id} className="flex items-center gap-2 text-xs text-gray-300">
                                <span className="flex-1 truncate">{m.email ?? m.user_id}</span>
                                <span className="text-[10px] uppercase tracking-wide text-gray-500 border border-line rounded-full px-2 py-0.5">
                                  {m.role}
                                </span>
                                {m.role !== "owner" && (
                                  <button onClick={() => removeMember(m.user_id)} className="text-gray-600 hover:text-red-400 transition" aria-label="Remove member">
                                    <X size={13} />
                                  </button>
                                )}
                              </li>
                            ))}
                          </ul>
                          <div className="flex gap-2">
                            <input
                              value={wsInvite}
                              onChange={(e) => setWsInvite(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") inviteMember();
                              }}
                              placeholder="Add member by account email…"
                              className="flex-1 rounded-xl bg-panel border border-line px-3 py-1.5 text-xs outline-none focus:border-accent/60 placeholder-gray-600"
                            />
                            <button
                              onClick={inviteMember}
                              disabled={!wsInvite.trim()}
                              className="rounded-lg bg-white/10 text-xs font-semibold px-3 py-1.5 text-gray-200 hover:bg-white/20 transition disabled:opacity-30"
                            >
                              Add
                            </button>
                          </div>
                          {wsInvites && (
                            <div className="space-y-1.5">
                              <div className="flex items-center gap-2">
                                <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Invite links</p>
                                <button
                                  onClick={createInvite}
                                  className="text-[11px] rounded-lg bg-white/5 border border-line px-2.5 py-1 text-gray-300 hover:bg-white/10 transition"
                                >
                                  + New link
                                </button>
                              </div>
                              {wsInvites.filter((i) => !i.revoked).length === 0 ? (
                                <p className="text-xs text-gray-600">No active links — create one to invite teammates without typing emails.</p>
                              ) : (
                                <ul className="space-y-1.5">
                                  {wsInvites
                                    .filter((i) => !i.revoked)
                                    .map((i) => (
                                      <li key={i.id} className="flex items-center gap-1.5 rounded-lg bg-panel border border-line px-2.5 py-1.5 text-[11px] text-gray-400">
                                        <span className="flex-1 truncate font-mono">{`/join/${i.token}`}</span>
                                        <CopyBtn text={`${window.location.origin}/join/${i.token}`} />
                                        <span className="text-gray-600 shrink-0">{i.expires_at ? `expires ${i.expires_at.slice(0, 10)}` : ""}</span>
                                        <button onClick={() => revokeInvite(i.id)} className="text-gray-600 hover:text-red-400 transition shrink-0" aria-label="Revoke invite">
                                          <X size={12} />
                                        </button>
                                      </li>
                                    ))}
                                </ul>
                              )}
                              <div className="flex gap-2">
                                <input
                                  value={wsEmails}
                                  onChange={(e) => setWsEmails(e.target.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter") emailInvites();
                                  }}
                                  placeholder="Email the invite — teammate@acme.com, mate2@acme.com…"
                                  className="flex-1 rounded-xl bg-panel border border-line px-3 py-1.5 text-xs outline-none focus:border-accent/60 placeholder-gray-600"
                                />
                                <button
                                  onClick={emailInvites}
                                  disabled={!wsEmails.trim()}
                                  title="Sent from your connected Gmail (Settings → Connected apps)"
                                  className="rounded-lg bg-white/10 text-xs font-semibold px-3 py-1.5 text-gray-200 hover:bg-white/20 transition disabled:opacity-30 shrink-0"
                                >
                                  📧 Email
                                </button>
                              </div>
                              <p className="text-[10px] text-gray-600">
                                Anyone with a link joins. Bind an active domain to this team (Domains card → Manage → Team gate)
                                and only that email domain can join — e.g. only @acme.com.
                              </p>
                            </div>
                          )}
                          {wsSeats && (
                            <div className="space-y-1">
                              <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Usage this month (per seat)</p>
                              {wsSeats.map((st) => (
                                <div key={st.user_id} className="flex justify-between text-xs text-gray-400">
                                  <span className="truncate">{st.email ?? st.user_id} · {st.plan}</span>
                                  <span className="shrink-0">{st.requests_month} req · {fmt(st.tokens_month)} tok</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          {/* Custom domains */}
          <div className="md:col-span-2">
            <Card icon={<Globe size={16} />} title="Custom domains">
              <p className="text-xs text-gray-500">
                Run Mood on your own domain for your business (white-label), or buy a new domain in real time —
                availability, pricing, secure checkout and auto-connection included.
                {domProviders?.registrar_env === "ote" && domProviders.registrar && (
                  <span className="text-yellow-500/90"> Registrar is in SANDBOX mode (no real registration/charge).</span>
                )}
              </p>
              {domMsg && <p className="text-xs text-yellow-500">{domMsg}</p>}
              <div className="flex gap-2 text-xs">
                {(
                  [
                    { id: "connect" as const, label: "🔗 Connect your domain" },
                    { id: "buy" as const, label: "🛒 Buy a domain" },
                  ] as const
                ).map((t) => (
                  <button
                    key={t.id}
                    onClick={() => setDomTab(t.id)}
                    className={`rounded-full border px-3 py-1.5 transition ${
                      domTab === t.id ? "bg-accent/15 border-accent/40 text-accent" : "bg-white/5 border-line text-gray-400 hover:text-gray-200"
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              {domTab === "connect" ? (
                <div className="space-y-3">
                  <div className="flex gap-2 flex-wrap">
                    <input
                      value={connectForm.domain}
                      onChange={(e) => setConnectForm((f) => ({ ...f, domain: e.target.value }))}
                      placeholder="chat.mybusiness.com"
                      className="flex-1 min-w-[220px] rounded-xl bg-base border border-line px-3 py-2 text-sm outline-none focus:border-accent/60 placeholder-gray-600"
                    />
                    <input
                      value={connectForm.brand}
                      onChange={(e) => setConnectForm((f) => ({ ...f, brand: e.target.value }))}
                      placeholder="Brand name (optional, e.g. Acme AI)"
                      className="w-44 rounded-xl bg-base border border-line px-3 py-2 text-sm outline-none focus:border-accent/60 placeholder-gray-600"
                    />
                    <button
                      onClick={connectDomain}
                      disabled={!connectForm.domain.trim() || domBusy}
                      className="rounded-xl bg-accent text-black text-sm font-semibold px-4 py-2 disabled:opacity-30 hover:brightness-110 transition shrink-0"
                    >
                      Connect
                    </button>
                  </div>
                  <p className="text-[11px] text-gray-600">
                    You&apos;ll get a TXT record (ownership) + a CNAME (traffic). Visitors on an active domain see
                    your brand name; HTTPS is issued automatically on first visit (Caddy on-demand TLS).
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  {!domProviders?.registrar || !domProviders?.stripe ? (
                    <p className="text-xs text-yellow-600">
                      ⚙️ Live purchase needs GODADDY_API_KEY/SECRET + STRIPE_SECRET_KEY configured on the server.
                      Until then, use the Connect tab with any domain you already own.
                    </p>
                  ) : null}
                  <div className="flex gap-2">
                    <input
                      value={buyQuery}
                      onChange={(e) => setBuyQuery(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") searchDomains();
                      }}
                      placeholder="Find your domain (e.g. acmeassistant or acme.ai)…"
                      disabled={!domProviders?.registrar || !domProviders?.stripe}
                      className="flex-1 rounded-xl bg-base border border-line px-3 py-2 text-sm outline-none focus:border-accent/60 placeholder-gray-600 disabled:opacity-40"
                    />
                    <button
                      onClick={searchDomains}
                      disabled={buyQuery.trim().length < 2 || domBusy || !domProviders?.registrar || !domProviders?.stripe}
                      className="rounded-xl bg-white/10 text-sm font-semibold px-4 py-2 text-gray-200 hover:bg-white/20 transition disabled:opacity-30 flex items-center gap-1.5 shrink-0"
                    >
                      <SearchCheck size={14} /> Search
                    </button>
                  </div>
                  {buyResults && (
                    <ul className="space-y-1.5">
                      {buyResults.map((r) => (
                        <li key={r.domain}>
                          <button
                            onClick={() => r.available && setBuyPick(buyPick?.domain === r.domain ? null : r)}
                            disabled={!r.available}
                            className={`w-full text-left rounded-xl border px-3 py-2 text-sm transition flex items-center gap-2 ${
                              !r.available
                                ? "border-line text-gray-600 cursor-not-allowed"
                                : buyPick?.domain === r.domain
                                  ? "bg-accent/10 border-accent/50 text-accent"
                                  : "bg-white/5 border-line text-gray-200 hover:bg-white/10"
                            }`}
                          >
                            <span className="flex-1 truncate">{r.domain}</span>
                            {r.available ? (
                              <span className="text-xs text-green-400 shrink-0">✓ {r.price_cents != null ? money(r.price_cents, r.currency) : "—"}/yr</span>
                            ) : (
                              <span className="text-xs text-gray-600 shrink-0">taken</span>
                            )}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  {buyPick && (
                    <div className="rounded-xl border border-accent/30 bg-accent/5 p-3 space-y-2">
                      <p className="text-xs font-semibold text-gray-200">
                        🛒 {buyPick.domain} — registrant contact (required by ICANN)
                      </p>
                      <div className="grid grid-cols-2 gap-2">
                        {(
                          [
                            ["name_first", "First name"], ["name_last", "Last name"],
                            ["email", "Email"], ["phone", "Phone (+1.555…)"],
                            ["address1", "Street address"], ["city", "City"],
                            ["state", "State / region"], ["postal_code", "Postal code"],
                          ] as [keyof typeof EMPTY_CONTACT, string][]
                        ).map(([k, ph]) => (
                          <input
                            key={k}
                            value={buyContact[k]}
                            onChange={(e) => setBuyContact((c) => ({ ...c, [k]: e.target.value }))}
                            placeholder={ph}
                            className="rounded-lg bg-base border border-line px-2.5 py-1.5 text-xs outline-none focus:border-accent/60 placeholder-gray-600"
                          />
                        ))}
                        <input
                          value={buyContact.country}
                          onChange={(e) => setBuyContact((c) => ({ ...c, country: e.target.value.toUpperCase().slice(0, 2) }))}
                          placeholder="Country (ISO-2, e.g. US/GH)"
                          className="rounded-lg bg-base border border-line px-2.5 py-1.5 text-xs outline-none focus:border-accent/60 placeholder-gray-600"
                        />
                        <input
                          value={buyBrand}
                          onChange={(e) => setBuyBrand(e.target.value)}
                          placeholder="Brand name (optional)"
                          className="rounded-lg bg-base border border-line px-2.5 py-1.5 text-xs outline-none focus:border-accent/60 placeholder-gray-600"
                        />
                      </div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <select
                          value={buyYears}
                          onChange={(e) => setBuyYears(Number(e.target.value))}
                          className="rounded-lg bg-base border border-line px-2 py-1.5 text-xs text-gray-200"
                        >
                          {[1, 2, 3, 5].map((y) => (
                            <option key={y} value={y}>{y} year{y > 1 ? "s" : ""}</option>
                          ))}
                        </select>
                        <button
                          onClick={buyDomain}
                          disabled={domBusy}
                          className="rounded-xl bg-accent text-black text-sm font-semibold px-4 py-2 disabled:opacity-30 hover:brightness-110 transition"
                        >
                          {domBusy ? "Preparing checkout…" : `Buy for ${buyPick.price_cents != null ? money(buyPick.price_cents * buyYears, buyPick.currency) : "—"}`}
                        </button>
                        <span className="text-[10px] text-gray-600">secure Stripe checkout · privacy included · auto-connected</span>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {domains && domains.length > 0 && (
                <div className="space-y-2 pt-1">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Your domains</p>
                  {domains.map((d) => (
                    <div key={d.id} className="rounded-xl bg-base border border-line px-3 py-2.5 space-y-2">
                      <div className="flex items-center gap-2 text-sm flex-wrap">
                        <span className="flex-1 min-w-[140px] truncate text-gray-200">
                          {d.domain}
                          {d.brand_name && <span className="text-gray-500"> · “{d.brand_name}”</span>}
                        </span>
                        <span
                          className={`text-[10px] uppercase tracking-wide rounded-full border px-2 py-0.5 shrink-0 ${
                            d.status === "active"
                              ? "text-green-400 border-green-400/30 bg-green-400/10"
                              : d.status === "failed"
                                ? "text-red-400 border-red-400/30 bg-red-400/10"
                                : "text-yellow-500 border-yellow-500/30 bg-yellow-500/10"
                          }`}
                        >
                          {d.kind === "purchased" ? `🛒 ${d.status}` : d.status === "pending_dns" ? "DNS pending" : d.status}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 text-[11px] flex-wrap">
                        <ExpiryPill d={d} />
                        {d.kind === "purchased" && (
                          <button
                            onClick={() => toggleRenew(d)}
                            title="Toggle auto-renew at the registrar"
                            className={`rounded-full border px-2 py-0.5 transition ${
                              d.auto_renew
                                ? "text-green-400 border-green-400/30 bg-green-400/10 hover:bg-green-400/20"
                                : "text-red-400 border-red-400/30 bg-red-400/10 hover:bg-red-400/20"
                            }`}
                          >
                            auto-renew {d.auto_renew ? "ON" : "OFF"}
                          </button>
                        )}
                        {d.accent && (
                          <span
                            className="inline-block h-3 w-3 rounded-full border border-line"
                            style={{ background: d.accent }}
                            title={`accent ${d.accent}`}
                          />
                        )}
                        {d.workspace_id && <span title="Invite links to this team only accept emails on this domain">🔒 team-gated</span>}
                        <button onClick={() => toggleManage(d)} className="rounded-lg bg-white/5 border border-line px-2.5 py-1 text-gray-300 hover:bg-white/10 transition">
                          Manage
                        </button>
                        <button onClick={() => toggleStats(d)} className="rounded-lg bg-white/5 border border-line px-2.5 py-1 text-gray-300 hover:bg-white/10 transition">
                          Analytics
                        </button>
                        {d.kind === "purchased" && (
                          <button onClick={() => refreshDomain(d.id)} title="Pull expiry + renewal state from the registrar" className="rounded-lg bg-white/5 border border-line px-2.5 py-1 text-gray-300 hover:bg-white/10 transition">
                            Sync
                          </button>
                        )}
                        {renewDue(d) && (
                          <button
                            onClick={() => renewDomain(d)}
                            disabled={domBusy}
                            title="Extend registration by 1 year (secure checkout → renewed at the registrar)"
                            className="rounded-lg bg-accent text-black font-semibold px-2.5 py-1 hover:brightness-110 transition disabled:opacity-40"
                          >
                            🔁 Renew now
                          </button>
                        )}
                        {d.kind === "connected" && d.status === "pending_dns" && (
                          <button onClick={() => verifyDomain(d.id)} className="rounded-lg bg-white/10 px-2.5 py-1 text-gray-200 hover:bg-white/20 transition">
                            Verify
                          </button>
                        )}
                        <button onClick={() => deleteDomain(d.id)} className="ml-auto text-gray-600 hover:text-red-400 transition" aria-label="Remove domain">
                          <X size={13} />
                        </button>
                      </div>
                      {d.dns && (
                        <div className="grid sm:grid-cols-2 gap-1.5 text-[11px] text-gray-500">
                          <div className="flex items-center gap-1.5 rounded-lg bg-panel border border-line px-2 py-1.5 min-w-0">
                            <span className="truncate">TXT {d.dns.txt_name} = {d.dns.txt_value}</span>
                            <CopyBtn text={d.dns.txt_value} />
                          </div>
                          <div className="flex items-center gap-1.5 rounded-lg bg-panel border border-line px-2 py-1.5 min-w-0">
                            <span className="truncate">CNAME {d.domain} → {d.dns.cname_target || "(see docs)"}</span>
                            {d.dns.cname_target && <CopyBtn text={d.dns.cname_target} />}
                          </div>
                        </div>
                      )}
                      {domOpen === d.id && domEdit && (
                        <div className="rounded-lg bg-panel border border-line p-3 space-y-3">
                          <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Branding & team gate</p>
                          <div className="grid sm:grid-cols-2 gap-2">
                            <input
                              value={domEdit.brand}
                              onChange={(e) => setDomEdit({ ...domEdit, brand: e.target.value })}
                              placeholder="Brand name (e.g. Acme AI)"
                              className="rounded-lg bg-base border border-line px-2.5 py-1.5 text-xs outline-none focus:border-accent/60 placeholder-gray-600"
                            />
                            <select
                              value={domEdit.workspace}
                              onChange={(e) => setDomEdit({ ...domEdit, workspace: e.target.value })}
                              className="rounded-lg bg-base border border-line px-2 py-1.5 text-xs text-gray-200"
                            >
                              <option value="">No team gate</option>
                              {(workspaces ?? [])
                                .filter((w) => w.owner)
                                .map((w) => (
                                  <option key={w.id} value={w.id}>🔒 Gate team: {w.name}</option>
                                ))}
                            </select>
                          </div>
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span className="text-[11px] text-gray-500">Accent</span>
                            {ACCENT_PRESETS.map((c) => (
                              <button
                                key={c}
                                onClick={() => setDomEdit({ ...domEdit, accent: c })}
                                className={`h-5 w-5 rounded-full border-2 transition ${domEdit.accent === c ? "border-white" : "border-transparent"}`}
                                style={{ background: c }}
                                aria-label={`accent ${c}`}
                              />
                            ))}
                            <input
                              type="color"
                              value={domEdit.accent}
                              onChange={(e) => setDomEdit({ ...domEdit, accent: e.target.value })}
                              className="h-6 w-8 cursor-pointer bg-transparent"
                              title="Custom accent color"
                            />
                            <span className="text-[10px] text-gray-600">{domEdit.accent}</span>
                          </div>
                          <div className="flex items-center gap-2 flex-wrap text-[11px]">
                            <span className="text-gray-500">Logo</span>
                            {domEdit.logo ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img src={domEdit.logo} alt="new logo preview" className="h-7 w-7 rounded object-contain border border-line" />
                            ) : d.has_logo ? (
                              <span className="text-gray-400">set ✓ (upload to replace)</span>
                            ) : (
                              <span className="text-gray-600">none</span>
                            )}
                            <label className="cursor-pointer rounded-lg bg-white/5 border border-line px-2.5 py-1 text-gray-300 hover:bg-white/10 transition">
                              Upload
                              <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={pickLogo} className="hidden" />
                            </label>
                            {(d.has_logo || domEdit.logo) && (
                              <button onClick={() => setDomEdit({ ...domEdit, logo: "" })} className="text-gray-600 hover:text-red-400 transition">
                                remove
                              </button>
                            )}
                            <span className="text-[10px] text-gray-600">≤150 KB PNG/WebP — shows in the sidebar & favicon</span>
                          </div>

                          {/* ⚔️ White-label arena: brand the debates, pick the judge, cap usage */}
                          <div className="rounded-lg border border-line bg-base/60 p-2.5 space-y-2">
                            <label className="flex items-center gap-2 text-[11px] font-semibold text-gray-300 cursor-pointer">
                              <input
                                type="checkbox"
                                checked={domEdit.arenaOn}
                                onChange={(e) => setDomEdit({ ...domEdit, arenaOn: e.target.checked })}
                                className="accent-[#7c9bff]"
                              />
                              ⚔️ White-label Arena on this domain
                              <span className="font-normal text-gray-600">— visitors&rsquo; debates run under your brand</span>
                            </label>
                            {domEdit.arenaOn && (
                              <>
                                <div className="grid sm:grid-cols-3 gap-2">
                                  <input
                                    value={domEdit.arenaBrand}
                                    onChange={(e) => setDomEdit({ ...domEdit, arenaBrand: e.target.value })}
                                    placeholder="Arena brand (e.g. Acme Arena)"
                                    className="rounded-lg bg-base border border-line px-2.5 py-1.5 text-xs outline-none focus:border-accent/60 placeholder-gray-600"
                                  />
                                  <select
                                    value={domEdit.arenaJudge}
                                    onChange={(e) => setDomEdit({ ...domEdit, arenaJudge: e.target.value })}
                                    className="rounded-lg bg-base border border-line px-2 py-1.5 text-xs text-gray-200"
                                  >
                                    {ARENA_JUDGES.map((j) => (
                                      <option key={j || "default"} value={j}>
                                        {j ? `⚖️ Judge: ${j}` : "⚖️ Judge: platform default"}
                                      </option>
                                    ))}
                                  </select>
                                  <input
                                    value={domEdit.arenaCap}
                                    onChange={(e) => setDomEdit({ ...domEdit, arenaCap: e.target.value.replace(/[^0-9]/g, "") })}
                                    placeholder="Daily cap/user (blank = plan)"
                                    inputMode="numeric"
                                    className="rounded-lg bg-base border border-line px-2.5 py-1.5 text-xs outline-none focus:border-accent/60 placeholder-gray-600"
                                  />
                                </div>
                                <div className="space-y-1.5">
                                  <p className="text-[10px] text-gray-500">
                                    Custom panel (blank = platform panel). Providers without API keys on the server are skipped.
                                  </p>
                                  {domEdit.arenaPanel.map((p, i) => (
                                    <div key={i} className="flex items-center gap-1.5">
                                      <select
                                        value={p.provider}
                                        onChange={(e) =>
                                          setDomEdit({
                                            ...domEdit,
                                            arenaPanel: domEdit.arenaPanel.map((q, j) =>
                                              j === i ? { ...q, provider: e.target.value } : q
                                            ),
                                          })
                                        }
                                        className="rounded-lg bg-base border border-line px-1.5 py-1 text-[11px] text-gray-200"
                                      >
                                        {ARENA_PROVIDERS.map((pr) => (
                                          <option key={pr} value={pr}>{pr}</option>
                                        ))}
                                      </select>
                                      <input
                                        value={p.model}
                                        onChange={(e) =>
                                          setDomEdit({
                                            ...domEdit,
                                            arenaPanel: domEdit.arenaPanel.map((q, j) =>
                                              j === i ? { ...q, model: e.target.value, label: e.target.value } : q
                                            ),
                                          })
                                        }
                                        placeholder="model id (e.g. grok-4)"
                                        className="flex-1 rounded-lg bg-base border border-line px-2 py-1 text-[11px] outline-none focus:border-accent/60 placeholder-gray-600"
                                      />
                                      <button
                                        onClick={() =>
                                          setDomEdit({ ...domEdit, arenaPanel: domEdit.arenaPanel.filter((_, j) => j !== i) })
                                        }
                                        className="text-gray-600 hover:text-red-400 transition text-xs px-1"
                                        aria-label="remove panelist"
                                      >
                                        ✕
                                      </button>
                                    </div>
                                  ))}
                                  {domEdit.arenaPanel.length < 6 && (
                                    <button
                                      onClick={() =>
                                        setDomEdit({
                                          ...domEdit,
                                          arenaPanel: [...domEdit.arenaPanel, { provider: "xai", model: "", label: "" }],
                                        })
                                      }
                                      className="text-[11px] text-accent hover:underline"
                                    >
                                      + Add panelist
                                    </button>
                                  )}
                                </div>
                              </>
                            )}
                          </div>
                          <div className="flex items-center gap-2 flex-wrap">
                            <button onClick={() => saveDomain(d.id)} className="rounded-lg bg-accent text-black text-xs font-semibold px-3 py-1.5 hover:brightness-110 transition">
                              Save
                            </button>
                            <button
                              onClick={() => {
                                setDomOpen(null);
                                setDomEdit(null);
                              }}
                              className="rounded-lg bg-white/5 border border-line text-xs px-3 py-1.5 text-gray-400 hover:bg-white/10 transition"
                            >
                              Cancel
                            </button>
                            <span className="text-[10px] text-gray-600">Team gate: invite links to that team will only accept @{d.domain} emails.</span>
                          </div>
                        </div>
                      )}
                      {domStatsOpen === d.id && (
                        <div className="rounded-lg bg-panel border border-line p-3 space-y-2">
                          {domStats[d.id] ? (
                            <>
                              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
                                {(
                                  [
                                    ["Requests today", domStats[d.id].today.requests],
                                    ["Users today", domStats[d.id].today.users],
                                    ["Requests · 14d", domStats[d.id].total_requests],
                                    ["Peak users/day", domStats[d.id].peak_daily_users],
                                  ] as [string, number][]
                                ).map(([label, v]) => (
                                  <div key={label} className="rounded-lg bg-base border border-line px-2 py-2">
                                    <p className="text-sm font-semibold text-gray-100">{fmt(v)}</p>
                                    <p className="text-[10px] text-gray-500">{label}</p>
                                  </div>
                                ))}
                              </div>
                              <div className="flex items-end gap-[3px] h-12">
                                {domStats[d.id].days.map((p) => {
                                  const max = Math.max(...domStats[d.id].days.map((x) => x.requests), 1);
                                  return (
                                    <div
                                      key={p.day}
                                      title={`${p.day}: ${p.requests} req · ${p.users} users`}
                                      className="flex-1 rounded-sm bg-accent/70"
                                      style={{ height: `${Math.max((p.requests / max) * 100, 3)}%` }}
                                    />
                                  );
                                })}
                              </div>
                              <div className="flex items-center justify-between gap-2">
                                <p className="text-[10px] text-gray-600">
                                  Requests & unique users hitting {d.domain} · real-time, 14-day window.
                                </p>
                                <button
                                  onClick={() => downloadDomainCsv(d)}
                                  disabled={csvBusy === d.id}
                                  className="shrink-0 rounded-lg bg-white/5 border border-line px-2 py-0.5 text-[10px] text-gray-300 hover:bg-white/10 transition disabled:opacity-40 flex items-center gap-1"
                                >
                                  {csvBusy === d.id ? <RefreshCw size={10} className="animate-spin" /> : "⤓"} CSV
                                </button>
                              </div>
                            </>
                          ) : (
                            <p className="text-xs text-gray-600">Loading analytics…</p>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>

          {/* Custom instructions */}
          <div className="md:col-span-2">
            <Card icon={<SlidersHorizontal size={16} />} title="Custom instructions">
              <p className="text-xs text-gray-500">
                Tell Mood how to behave in <b>every</b> conversation — tone, format, language, expertise level
                (e.g. “Answer like a senior engineer; keep answers concise; always show code in Python”).
              </p>
              <textarea
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                rows={4}
                maxLength={2000}
                placeholder="How should Mood respond to you?"
                className="w-full rounded-xl bg-base border border-line px-4 py-3 text-sm outline-none focus:border-accent/60 placeholder-gray-600 resize-y"
              />
              <div className="flex items-center gap-3">
                <button
                  onClick={saveInstructions}
                  className="rounded-xl bg-accent text-black text-sm font-semibold px-4 py-2 hover:brightness-110 transition"
                >
                  Save instructions
                </button>
                {instrSaved && <span className="text-xs text-green-400">Saved ✓ — applies to all future chats</span>}
                <span className="text-[10px] text-gray-600 ml-auto">{instructions.length}/2000</span>
              </div>
            </Card>
          </div>

          {/* Memory */}
          <div className="md:col-span-2">
            <Card
              icon={<Brain size={16} />}
              title={`What Mood remembers ${mems ? `(${mems.length})` : ""}`}
            >
              <p className="text-xs text-gray-500">
                Mood remembers durable facts about you and what your past conversations were about — that&apos;s how
                it picks up where you left off in new chats. Delete anything you don&apos;t want Mood to know.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={loadMemories}
                  className="flex items-center gap-1.5 text-xs rounded-lg bg-white/5 border border-line px-3 py-1.5 text-gray-300 hover:bg-white/10 transition"
                >
                  <RefreshCw size={12} /> Refresh
                </button>
                {mems && mems.length > 0 && (
                  <button
                    onClick={clearAll}
                    className="flex items-center gap-1.5 text-xs rounded-lg bg-red-400/10 border border-red-400/30 px-3 py-1.5 text-red-400 hover:bg-red-400/20 transition"
                  >
                    <Trash2 size={12} /> Clear all
                  </button>
                )}
              </div>
              {memError && <p className="text-xs text-yellow-500">{memError}</p>}
              {mems && mems.length === 0 && <p className="text-sm text-gray-600">Nothing stored yet — chat for a while first.</p>}
              {mems && mems.length > 0 && (
                <div className="space-y-4">
                  {mems.some((m) => m.category !== "chat") && (
                    <div className="space-y-2">
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">🧠 Facts about you</p>
                      <ul className="space-y-2">
                        {mems.filter((m) => m.category !== "chat").map((m) => (
                          <li key={m.id} className="flex items-start gap-2 rounded-xl bg-base border border-line px-3 py-2.5">
                            <span className="text-[10px] uppercase tracking-wide text-gray-500 border border-line rounded-full px-2 py-0.5 shrink-0 mt-0.5">
                              {m.category ?? "fact"}
                            </span>
                            <span className="flex-1 text-sm text-gray-300">{m.fact}</span>
                            <button onClick={() => deleteMem(m.id)} className="text-gray-600 hover:text-red-400 transition shrink-0" aria-label="Delete memory">
                              <X size={14} />
                            </button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {mems.some((m) => m.category === "chat") && (
                    <div className="space-y-2">
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">💬 Past conversations</p>
                      <ul className="space-y-2">
                        {mems.filter((m) => m.category === "chat").map((m) => (
                          <li key={m.id} className="flex items-start gap-2 rounded-xl bg-base border border-line px-3 py-2.5">
                            <span className="flex-1 text-sm text-gray-300">
                              {m.title && <span className="font-semibold text-gray-200">{m.title} — </span>}
                              {m.fact}
                            </span>
                            <button onClick={() => deleteMem(m.id)} className="text-gray-600 hover:text-red-400 transition shrink-0" aria-label="Forget this conversation">
                              <X size={14} />
                            </button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </Card>

            {/* ☠️ Danger zone — app-store-required account deletion */}
            <Card icon={<Trash2 size={16} className="text-red-400" />} title="Danger zone">
              <div className="space-y-3">
                <p className="text-xs text-gray-400">
                  Permanently delete your Mood AI account — chats, uploads, designs, films, edits, orders, memory,
                  plugin tokens, and teams you own. <span className="font-semibold text-red-300">This is instant and cannot be undone.</span>{" "}
                  Details at <a href="/account-deletion" className="text-accent underline underline-offset-2">/account-deletion</a>.
                </p>
                {!confirmDel ? (
                  <button onClick={() => setConfirmDel(true)}
                    className="touch-manipulation rounded-xl border border-red-500/40 px-4 py-2 text-xs font-semibold text-red-400 hover:bg-red-500/10 transition">
                    Delete my account…
                  </button>
                ) : (
                  <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-3 space-y-2.5">
                    <p className="text-xs text-red-300">Type your password to confirm permanent deletion:</p>
                    <input type="password" value={delPw} onChange={(e) => setDelPw(e.target.value)}
                      placeholder="Your password" autoComplete="current-password"
                      className="w-full max-w-sm rounded-xl border border-line bg-base px-3 py-2 text-sm outline-none focus:border-red-500/60" />
                    {delMsg && <p className="text-xs text-red-400">{delMsg}</p>}
                    <div className="flex flex-wrap gap-2">
                      <button onClick={deleteAccount} disabled={delBusy || !delPw}
                        className="touch-manipulation rounded-xl bg-red-600 px-4 py-2.5 text-xs font-bold text-white hover:bg-red-500 disabled:opacity-40 transition">
                        {delBusy ? "Deleting…" : "🗑 Delete forever"}
                      </button>
                      <button onClick={() => { setConfirmDel(false); setDelPw(""); setDelMsg(""); }}
                        className="touch-manipulation rounded-xl border border-line px-4 py-2.5 text-xs text-gray-300 hover:border-accent/50 transition">
                        Keep my account
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </Card>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
