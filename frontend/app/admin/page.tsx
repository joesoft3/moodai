"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, BarChart3, Bell, KeyRound, Puzzle, RefreshCw, Search, Send, ShieldCheck, Smartphone, Trash2, UserCog, Users } from "lucide-react";
import AppShell from "@/components/AppShell";
import { apiFetch } from "@/lib/api";

interface Overview {
  stats: {
    users: number;
    conversations: number;
    messages: number;
    workspaces: number;
    devices?: number;
    domains_active: number;
    tokens_month: number;
    active_users_week: number;
  };
  recent_users: AdminUser[];
  capabilities: Record<string, boolean | string>;
}

interface AdminUser {
  id: string;
  email: string;
  display_name: string | null;
  plan: string;
  is_admin: boolean;
  created_at: string | null;
  conversations?: number;
  tokens_month?: number;
}

interface Gate {
  signup_open: boolean;
  app_password_set: boolean;
  admin_emails: string[];
}

interface DevicesInfo {
  total: number;
  by_platform: Record<string, number>;
  recent: { platform: string; email: string; created_at: string | null; last_seen_at: string | null }[];
}

interface Analytics {
  signups_14d: { day: string; count: number }[];
  active_14d: { day: string; count: number }[];
  usage_mix: { kind: string; runs: number; tokens: number }[];
  arena: { runs_total: number; runs_7d: number; unique_users: number };
  revenue: { pro_subscribers: number; price_cents: number; currency: string; live_price: boolean; mrr_cents: number };
  top_users_month: { email: string; tokens: number }[];
}

function fmt(n: number): string {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`;
}

/** Tiny SVG bar series (no chart lib — keeps the bundle lean). */
function Bars({ data, color }: { data: { day: string; count: number }[]; color: string }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  return (
    <div>
      <div className="flex items-end gap-[3px] h-20">
        {data.map((d) => (
          <div
            key={d.day}
            title={`${d.day.slice(5)}: ${d.count}`}
            className="flex-1 rounded-t-sm transition-all hover:brightness-125"
            style={{ height: `${Math.max(4, (d.count / max) * 100)}%`, background: color }}
          />
        ))}
      </div>
      <div className="flex justify-between text-[9px] text-gray-600 mt-1">
        <span>{data[0]?.day.slice(5)}</span>
        <span>{data[data.length - 1]?.day.slice(5)}</span>
      </div>
    </div>
  );
}

function Card({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <section className="bg-panel border border-line rounded-2xl p-5 space-y-4">
      <header className="flex items-center gap-2 text-sm font-semibold">
        <span className="text-accent">{icon}</span> {title}
      </header>
      {children}
    </section>
  );
}

export default function AdminPage() {
  const [denied, setDenied] = useState(false);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [gate, setGate] = useState<Gate | null>(null);
  const [gateMsg, setGateMsg] = useState("");
  const [newPw, setNewPw] = useState("");
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [devices, setDevices] = useState<DevicesInfo | null>(null);
  const [pushTitle, setPushTitle] = useState("🔔 Mood AI push test");
  const [pushBody, setPushBody] = useState("If you can read this, push is wired end-to-end. 🎉");
  const [pushMsg, setPushMsg] = useState("");
  const [pushBusy, setPushBusy] = useState(false);
  const [q, setQ] = useState("");
  const [userMsg, setUserMsg] = useState("");

  const loadAll = useCallback(async () => {
    try {
      const [o, g, u, a, d] = await Promise.all([
        apiFetch<Overview>("/admin/overview"),
        apiFetch<Gate>("/admin/settings"),
        apiFetch<{ users: AdminUser[] }>(`/admin/users${q ? `?q=${encodeURIComponent(q)}` : ""}`),
        apiFetch<Analytics>("/admin/analytics"),
        apiFetch<DevicesInfo>("/admin/devices"),
      ]);
      setOverview(o);
      setGate(g);
      setUsers(u.users);
      setAnalytics(a);
      setDevices(d);
      setDenied(false);
    } catch (e: any) {
      if ((e.message ?? "").includes("Admin only")) setDenied(true);
    }
  }, [q]);

  async function sendPushTest() {
    setPushBusy(true);
    setPushMsg("");
    try {
      const r = await apiFetch<{ sent: number }>("/admin/push-test", {
        method: "POST",
        body: JSON.stringify({ title: pushTitle, body: pushBody }),
      });
      setPushMsg(`✅ Delivered to ${r.sent} of your device${r.sent === 1 ? "" : "s"}.`);
    } catch (e: any) {
      setPushMsg("⚠️ " + (e.message ?? "Push test failed"));
    } finally {
      setPushBusy(false);
    }
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function saveGate(patch: { signup_open?: boolean; app_password?: string }) {
    setGateMsg("");
    try {
      const g = await apiFetch<Gate>("/admin/settings", { method: "PUT", body: JSON.stringify(patch) });
      setGate(g);
      setNewPw("");
      setGateMsg("✅ Saved.");
    } catch (e: any) {
      setGateMsg("⚠️ " + (e.message ?? "Save failed"));
    }
  }

  async function callUser(path: string, body: any) {
    setUserMsg("");
    try {
      await apiFetch(path, { method: "POST", body: JSON.stringify(body) });
      await loadAll();
    } catch (e: any) {
      setUserMsg("⚠️ " + (e.message ?? "Action failed"));
    }
  }

  async function resetPassword(u: AdminUser) {
    const pw = window.prompt(`New password for ${u.email} (min 8 chars):`);
    if (!pw) return;
    if (pw.length < 8) {
      setUserMsg("⚠️ Password must be at least 8 characters.");
      return;
    }
    await callUser(`/admin/users/${u.id}/password`, { password: pw });
    setUserMsg(`✅ Password reset for ${u.email}.`);
  }

  if (denied) {
    return (
      <AppShell title="Owner panel">
        <div className="flex-1 flex items-center justify-center px-4">
          <p className="text-sm text-gray-500">🔒 Owner access only — this account isn&apos;t an admin.</p>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell title="Owner panel">
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin px-3 sm:px-4 py-6 compact-v">
        <div className="max-w-5xl 2xl:max-w-6xl mx-auto grid gap-4 md:grid-cols-2">
          {/* Overview */}
          <div className="md:col-span-2">
            <Card icon={<Activity size={16} />} title="Platform overview">
              {!overview ? (
                <p className="text-sm text-gray-600">Loading…</p>
              ) : (
                <>
                  <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2 text-center">
                    {(
                      [
                        ["Users", overview.stats.users],
                        ["Active · 7d", overview.stats.active_users_week],
                        ["Conversations", overview.stats.conversations],
                        ["Messages", overview.stats.messages],
                        ["Teams", overview.stats.workspaces],
                        ["Push devices", overview.stats.devices ?? 0],
                        ["Active domains", overview.stats.domains_active],
                        ["Tokens · month", overview.stats.tokens_month],
                      ] as [string, number][]
                    ).map(([label, v]) => (
                      <div key={label} className="rounded-xl bg-base border border-line px-2 py-3">
                        <p className="text-base font-semibold text-gray-100">{fmt(v)}</p>
                        <p className="text-[10px] text-gray-500">{label}</p>
                      </div>
                    ))}
                  </div>
                  <div className="flex flex-wrap gap-2 text-[11px]">
                    {Object.entries(overview.capabilities).map(([k, v]) => (
                      <span
                        key={k}
                        className={`rounded-full border px-2.5 py-1 ${
                          v ? "text-green-400 border-green-400/30 bg-green-400/10" : "text-gray-500 border-line"
                        }`}
                      >
                        {k === "registrar_env" ? `registrar: ${v}` : `${k}${v ? "" : " (off)"}`}
                      </span>
                    ))}
                  </div>
                </>
              )}
            </Card>
          </div>

          {/* 📊 Analytics: growth, activity, usage mix, arena, revenue */}
          <Card icon={<BarChart3 size={16} />} title="Analytics — growth · usage · revenue">
            {!analytics ? (
              <p className="text-sm text-gray-600">Loading…</p>
            ) : (
              <div className="space-y-5">
                <div className="grid sm:grid-cols-2 gap-4">
                  <div className="rounded-xl bg-base border border-line p-3">
                    <p className="text-[11px] text-gray-500 mb-2">✨ New signups (14 days)</p>
                    <Bars data={analytics.signups_14d} color="#7c9bff" />
                  </div>
                  <div className="rounded-xl bg-base border border-line p-3">
                    <p className="text-[11px] text-gray-500 mb-2">🔥 Active users (14 days)</p>
                    <Bars data={analytics.active_14d} color="#34d399" />
                  </div>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
                  {(
                    [
                      ["⚔️ Arena runs · all time", fmt(analytics.arena.runs_total)],
                      ["⚔️ Arena runs · 7d", fmt(analytics.arena.runs_7d)],
                      ["⚔️ Debaters (users)", fmt(analytics.arena.unique_users)],
                      [
                        "💳 MRR (est.)",
                        `${analytics.revenue.currency.toUpperCase()} ${(analytics.revenue.mrr_cents / 100).toFixed(0)}${analytics.revenue.live_price ? "" : " ≈"}`,
                      ],
                    ] as [string, string][]
                  ).map(([label, v]) => (
                    <div key={label} className="rounded-xl bg-base border border-line px-2 py-3">
                      <p className="text-base font-semibold text-gray-100">{v}</p>
                      <p className="text-[10px] text-gray-500">{label}</p>
                    </div>
                  ))}
                </div>
                <p className="text-[10px] text-gray-600 -mt-3">
                  💳 {analytics.revenue.pro_subscribers} Pro subscriber{analytics.revenue.pro_subscribers === 1 ? "" : "s"} ×{" "}
                  {(analytics.revenue.price_cents / 100).toFixed(0)} {analytics.revenue.currency.toUpperCase()}
                  {analytics.revenue.live_price
                    ? " (live price from Stripe)"
                    : " — estimate: set STRIPE_SECRET_KEY + STRIPE_PRICE_ID for the live price"}
                </p>

                <div className="grid sm:grid-cols-2 gap-4">
                  <div className="rounded-xl bg-base border border-line p-3">
                    <p className="text-[11px] text-gray-500 mb-2">🧮 Usage mix — runs (30d)</p>
                    <div className="space-y-1.5">
                      {analytics.usage_mix.length === 0 && <p className="text-xs text-gray-600">No metered runs yet.</p>}
                      {analytics.usage_mix.map((m) => {
                        const total = Math.max(1, ...analytics.usage_mix.map((x) => x.runs));
                        return (
                          <div key={m.kind} className="text-[11px]">
                            <div className="flex justify-between text-gray-400">
                              <span>{m.kind}</span>
                              <span className="text-gray-600">
                                {fmt(m.runs)} runs · {fmt(m.tokens)} tok
                              </span>
                            </div>
                            <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
                              <div className="h-full bg-accent/70 rounded-full" style={{ width: `${(m.runs / total) * 100}%` }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                  <div className="rounded-xl bg-base border border-line p-3">
                    <p className="text-[11px] text-gray-500 mb-2">🏆 Heaviest users — tokens this month</p>
                    <div className="space-y-1">
                      {analytics.top_users_month.length === 0 && <p className="text-xs text-gray-600">Nothing yet.</p>}
                      {analytics.top_users_month.map((u, i) => (
                        <p key={u.email} className="text-[11px] text-gray-400 flex justify-between gap-2">
                          <span className="truncate">
                            {i + 1}. {u.email}
                          </span>
                          <span className="text-gray-600 shrink-0">{fmt(u.tokens)}</span>
                        </p>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </Card>

          {/* 🔔 Push & devices (dashboard v2) */}
          <Card icon={<Bell size={16} />} title="Push & devices">
            {!devices ? (
              <p className="text-sm text-gray-600">Loading…</p>
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
                  <div className="rounded-xl bg-base border border-line px-2 py-3">
                    <p className="text-base font-semibold text-gray-100">{fmt(devices.total)}</p>
                    <p className="text-[10px] text-gray-500">Registered devices</p>
                  </div>
                  {Object.entries(devices.by_platform).map(([platform, n]) => (
                    <div key={platform} className="rounded-xl bg-base border border-line px-2 py-3">
                      <p className="text-base font-semibold text-gray-100 flex items-center justify-center gap-1">
                        <Smartphone size={13} className="text-accent" /> {fmt(n)}
                      </p>
                      <p className="text-[10px] text-gray-500">{platform}</p>
                    </div>
                  ))}
                </div>

                <div className="rounded-xl bg-base border border-line p-3 space-y-2">
                  <p className="text-[11px] text-gray-500">Send a real test push to YOUR devices</p>
                  <input
                    value={pushTitle}
                    onChange={(e) => setPushTitle(e.target.value)}
                    maxLength={80}
                    className="w-full rounded-lg bg-panel border border-line px-3 py-2 text-sm outline-none focus:border-accent/60"
                    placeholder="Title"
                  />
                  <textarea
                    value={pushBody}
                    onChange={(e) => setPushBody(e.target.value)}
                    rows={2}
                    maxLength={240}
                    className="w-full rounded-lg bg-panel border border-line px-3 py-2 text-sm outline-none focus:border-accent/60 resize-none"
                    placeholder="Body"
                  />
                  <div className="flex items-center gap-2">
                    <button
                      onClick={sendPushTest}
                      disabled={pushBusy || !pushTitle.trim()}
                      className="rounded-xl bg-accent text-black text-sm font-semibold px-4 py-2 disabled:opacity-40 hover:brightness-110 transition flex items-center gap-1.5"
                    >
                      <Send size={13} /> {pushBusy ? "Sending…" : "Send test push"}
                    </button>
                    {pushMsg && <p className="text-[11px] text-yellow-500">{pushMsg}</p>}
                  </div>
                  <p className="text-[10px] text-gray-600">
                    Needs FCM_PROJECT_ID + FCM_SERVICE_ACCOUNT_JSON on the backend and the Android app signed in once
                    on your phone (300s per-kind cooldown applies).
                  </p>
                </div>

                {devices.recent.length > 0 && (
                  <div>
                    <p className="text-[11px] text-gray-500 mb-1.5">Recent registrations</p>
                    <ul className="space-y-1 text-[11px]">
                      {devices.recent.map((d, i) => (
                        <li key={i} className="flex items-center gap-2 rounded-lg bg-base border border-line px-2.5 py-1.5">
                          <span className="rounded-full border border-line px-2 py-0.5 text-gray-400">{d.platform}</span>
                          <span className="text-gray-300 truncate">{d.email}</span>
                          <span className="text-gray-600 ml-auto shrink-0">{(d.last_seen_at ?? d.created_at ?? "").slice(0, 10)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </Card>

          {/* App access gate */}
          <Card icon={<KeyRound size={16} />} title="App access control">
            <p className="text-xs text-gray-500">
              Control who can sign up for this deployment. The app password is stored hashed — rotating it
              locks out new signups without the new code instantly.
            </p>
            {gateMsg && <p className="text-xs text-yellow-500">{gateMsg}</p>}
            {gate && (
              <>
                <div className="flex items-center gap-3">
                  <span className="text-sm text-gray-300 flex-1">Open signups</span>
                  <button
                    onClick={() => saveGate({ signup_open: !gate.signup_open })}
                    className={`text-xs rounded-full border px-3 py-1.5 transition ${
                      gate.signup_open
                        ? "text-green-400 border-green-400/30 bg-green-400/10 hover:bg-green-400/20"
                        : "text-red-400 border-red-400/30 bg-red-400/10 hover:bg-red-400/20"
                    }`}
                  >
                    {gate.signup_open ? "OPEN — anyone can register" : "CLOSED — invite-only"}
                  </button>
                </div>
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      value={newPw}
                      onChange={(e) => setNewPw(e.target.value)}
                      placeholder={gate.app_password_set ? "Rotate app access code…" : "Set an app access code…"}
                      className="flex-1 rounded-xl bg-base border border-line px-3 py-2 text-sm outline-none focus:border-accent/60 placeholder-gray-600"
                    />
                    <button
                      onClick={() => newPw.trim().length >= 8 && saveGate({ app_password: newPw.trim() })}
                      disabled={newPw.trim().length < 8}
                      className="rounded-xl bg-accent text-black text-sm font-semibold px-4 py-2 disabled:opacity-30 hover:brightness-110 transition shrink-0"
                    >
                      {gate.app_password_set ? "Rotate" : "Enable"}
                    </button>
                    {gate.app_password_set && (
                      <button
                        onClick={() => confirm("Remove the app access code? Anyone (subject to signup toggle) can register.") && saveGate({ app_password: "" })}
                        className="rounded-xl bg-red-400/10 border border-red-400/30 text-sm px-3 py-2 text-red-400 hover:bg-red-400/20 transition shrink-0"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                  <p className="text-[11px] text-gray-600">
                    Gate status: {gate.app_password_set ? "🔒 code required to sign up" : "🔓 no code required"}
                    {gate.admin_emails.length > 0 && ` · env owners: ${gate.admin_emails.join(", ")}`}
                  </p>
                </div>
              </>
            )}
          </Card>

          {/* Capabilities quick links */}
          <Card icon={<Puzzle size={16} />} title="Owner shortcuts">
            <div className="grid grid-cols-2 gap-2 text-xs">
              <a href="/settings" className="rounded-xl bg-base border border-line px-3 py-2.5 hover:bg-white/5 transition">
                ⚙️ Runtime settings →
              </a>
              <a href="/settings" className="rounded-xl bg-base border border-line px-3 py-2.5 hover:bg-white/5 transition">
                🌐 Domains & white-label →
              </a>
              <a href="/files" className="rounded-xl bg-base border border-line px-3 py-2.5 hover:bg-white/5 transition">
                🗂 Files manager →
              </a>
              <a href="/chat" className="rounded-xl bg-base border border-line px-3 py-2.5 hover:bg-white/5 transition">
                💬 Back to chat →
              </a>
            </div>
            <p className="text-[11px] text-gray-600">
              Server-side admins: users with the admin flag or emails in <code>ADMIN_EMAILS</code>. Every endpoint
              here re-checks admin rights — this page is only a view.
            </p>
          </Card>

          {/* Users */}
          <div className="md:col-span-2">
            <Card icon={<Users size={16} />} title="User administration">
              <div className="flex gap-2">
                <div className="flex-1 relative">
                  <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
                  <input
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && loadAll()}
                    placeholder="Search by email or name…"
                    className="w-full rounded-xl bg-base border border-line pl-8 pr-3 py-2 text-sm outline-none focus:border-accent/60 placeholder-gray-600"
                  />
                </div>
                <button
                  onClick={loadAll}
                  className="rounded-xl bg-white/5 border border-line px-3 py-2 text-gray-300 hover:bg-white/10 transition shrink-0"
                  title="Refresh"
                >
                  <RefreshCw size={14} />
                </button>
              </div>
              {userMsg && <p className="text-xs text-yellow-500">{userMsg}</p>}
              {!users ? (
                <p className="text-sm text-gray-600">Loading…</p>
              ) : users.length === 0 ? (
                <p className="text-sm text-gray-600">No users found.</p>
              ) : (
                <ul className="space-y-2">
                  {users.map((u) => (
                    <li key={u.id} className="rounded-xl bg-base border border-line px-3 py-2.5 space-y-2">
                      <div className="flex items-center gap-2 text-sm flex-wrap">
                        <span className="text-gray-200 truncate">{u.display_name || u.email}</span>
                        {u.display_name && <span className="text-gray-500 text-xs truncate">{u.email}</span>}
                        <span
                          className={`text-[10px] uppercase tracking-wide rounded-full border px-2 py-0.5 ${
                            u.plan === "pro" ? "text-accent border-accent/40 bg-accent/10" : "text-gray-500 border-line"
                          }`}
                        >
                          {u.plan}
                        </span>
                        {u.is_admin && (
                          <span className="text-[10px] uppercase tracking-wide rounded-full border px-2 py-0.5 text-yellow-500 border-yellow-500/30 bg-yellow-500/10">
                            admin
                          </span>
                        )}
                        <span className="text-[10px] text-gray-600 ml-auto shrink-0">
                          {(u.created_at ?? "").slice(0, 10)} · {u.conversations ?? 0} chats · {fmt(u.tokens_month ?? 0)} tok/mo
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 text-[11px] flex-wrap">
                        <button
                          onClick={() => callUser(`/admin/users/${u.id}/plan`, { plan: u.plan === "pro" ? "free" : "pro" })}
                          className="rounded-lg bg-white/5 border border-line px-2.5 py-1 text-gray-300 hover:bg-white/10 transition"
                        >
                          → {u.plan === "pro" ? "free" : "pro"} plan
                        </button>
                        <button
                          onClick={() => resetPassword(u)}
                          className="rounded-lg bg-white/5 border border-line px-2.5 py-1 text-gray-300 hover:bg-white/10 transition flex items-center gap-1"
                        >
                          <UserCog size={11} /> Reset password
                        </button>
                        <button
                          onClick={() => callUser(`/admin/users/${u.id}/admin`, { is_admin: !u.is_admin })}
                          className="rounded-lg bg-white/5 border border-line px-2.5 py-1 text-gray-300 hover:bg-white/10 transition flex items-center gap-1"
                        >
                          <ShieldCheck size={11} /> {u.is_admin ? "Revoke admin" : "Make admin"}
                        </button>
                        <button
                          onClick={async () => {
                            if (!confirm(`Delete ${u.email} and ALL their data? This cannot be undone.`)) return;
                            setUserMsg("");
                            try {
                              await apiFetch(`/admin/users/${u.id}`, { method: "DELETE" });
                              await loadAll();
                              setUserMsg(`Deleted ${u.email}.`);
                            } catch (e: any) {
                              setUserMsg("⚠️ " + (e.message ?? "Delete failed"));
                            }
                          }}
                          className="rounded-lg bg-red-400/10 border border-red-400/30 px-2.5 py-1 text-red-400 hover:bg-red-400/20 transition flex items-center gap-1"
                        >
                          <Trash2 size={11} /> Delete
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
