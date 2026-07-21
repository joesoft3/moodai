"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AudioLines, Brush, Clapperboard, Download, Image as ImageIcon, Link2Off, Share2, Telescope } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import { streamChat } from "@/lib/stream";
import { LAST_CONV_KEY, useConversations } from "@/lib/conversations";
import AppShell from "@/components/AppShell";
import MessageBubble, { ChatMsg } from "@/components/MessageBubble";
import Composer, { FileChip } from "@/components/Composer";
import ArenaPanel, { ArenaEvt } from "@/components/ArenaPanel";
import ThinkingPanel, { ThinkEvt } from "@/components/ThinkingPanel";
import ModelPicker from "@/components/ModelPicker";

/** 🧠 Only these models support extended reasoning (grok-4-fast has no thinking trace). */
const THINKABLE = ["grok-4", "auto", "grok-code-fast-1"];

function EmptyState() {
  return (
    <div className="flex items-center justify-center min-h-[58vh] select-none">
      {/* 🏠 Grok-clean home: the Mood AI ✦ mark itself as a faint, theme-aware
          watermark (inline SVG → crisp at any density, currentColor in both themes) */}
      <svg
        viewBox="0 0 64 64"
        aria-hidden
        className="w-44 sm:w-56 opacity-[0.07] text-accent pointer-events-none"
      >
        <path
          fill="currentColor"
          d="M32 2c2.2 14.9 7.6 22.4 15 25.5C56 31 60 32 62 32c-2 0-6 1-15 4.5C39.6 39.6 34.2 47.1 32 62c-2.2-14.9-7.6-22.4-15-25.5C8 33 4 32 2 32c2 0 6-1 15-4.5C24.4 24.4 29.8 16.9 32 2Z"
        />
      </svg>
    </div>
  );
}

export default function ChatPage() {
  const router = useRouter();
  const { convs, activeId, setActiveId, refresh } = useConversations();
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [files, setFiles] = useState<FileChip[]>([]);
  const [busy, setBusy] = useState(false);
  const [voiceMode, setVoiceMode] = useState(false);
  const [agentMode, setAgentModeState] = useState(false);
  const [deepMode, setDeepModeState] = useState(false);
  const [pluginMode, setPluginMode] = useState(false);
  const [model, setModel] = useState("auto");
  const [thinkOn, setThinkOn] = useState(false);
  const [arenaMode, setArenaMode] = useState(false);
  const [arenaExtra, setArenaExtra] = useState("");
  const [shared, setShared] = useState(false);
  const [shareMsg, setShareMsg] = useState("");
  const [wsId, setWsId] = useState<string | null>(null);
  const [wsName, setWsName] = useState("");
  const [billingNote, setBillingNote] = useState("");
  const [billingCta, setBillingCta] = useState<"" | "upgrade">("");
  const [teamConvs, setTeamConvs] = useState<{ id: string; title: string; author: string }[] | null>(null);
  const [showTeam, setShowTeam] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const lastLoaded = useRef<string | null>(null);
  const skipNextLoad = useRef(false);
  const busyRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const restoredRef = useRef(false);

  // Agent mode, Deep search and Arena are mutually exclusive
  function setAgentMode(v: boolean) {
    setAgentModeState(v);
    if (v) {
      setDeepModeState(false);
      setArenaMode(false);
    }
  }
  function setDeepMode(v: boolean) {
    setDeepModeState(v);
    if (v) {
      setAgentModeState(false);
      setArenaMode(false);
    }
  }

  function stop() {
    abortRef.current?.abort();
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs]);

  // Team workspace mode via /chat?ws=<id> (linked from Settings → Teams)
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    // Return from Stripe checkout (arena premium upgrade): ?billing=success|cancelled
    const billing = q.get("billing");
    const id = q.get("ws");
    if (billing) {
      if (billing === "cancelled") {
        setBillingNote(
          "⚔️ Arena needs Pro. Pick/enable another channel in Settings → Providers, then retry the arena."
        );
        setArenaMode(true);
      } else if (billing === "success") {
        setBillingNote("🎉 Welcome to Pro — arena, thinking models & premium quota unlocked.");
        setTimeout(() => {
          setBillingNote("");
          setBillingCta("");
        }, 9000);
      }
      window.history.replaceState({}, "", window.location.pathname + (id ? `?ws=${id}` : ""));
    }
    if (!id) return;
    setWsId(id);
    Promise.all([
      apiFetch<{ name: string }>(`/workspaces/${id}`),
      apiFetch<{ conversations: { id: string; title: string; author: string }[] }>(`/workspaces/${id}/conversations`),
    ])
      .then(([d, c]) => {
        setWsName(d.name as any);
        setTeamConvs(c.conversations);
      })
      .catch(() => setWsId(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Resume the conversation you last had open (once per visit, when nothing is selected)
  useEffect(() => {
    if (restoredRef.current || activeId || convs.length === 0 || wsId) return;
    restoredRef.current = true;
    try {
      const last = localStorage.getItem(LAST_CONV_KEY);
      if (last && convs.some((c) => c.id === last)) setActiveId(last);
    } catch {
      /* storage unavailable */
    }
  }, [convs, activeId, setActiveId, wsId]);

  // Load messages whenever the globally-selected conversation changes
  useEffect(() => {
    if (!activeId) {
      lastLoaded.current = null;
      setMsgs([]);
      return;
    }
    if (skipNextLoad.current) {
      skipNextLoad.current = false;
      lastLoaded.current = activeId;
      return;
    }
    if (lastLoaded.current === activeId || busyRef.current) return;
    lastLoaded.current = activeId;
    setMsgs([]);
    setFiles([]);
    apiFetch<any>(`/conversations/${activeId}`)
      .then((d) => {
        const authors: Record<string, string> = d.authors ?? {};
        setMsgs(
          d.messages.map((m: any) => {
            const meta = m.meta ?? {};
            return {
              role: m.role,
              content: m.content,
              author: m.user_id ? (authors[m.user_id] ?? "member") : undefined,
              arena:
                meta.mode === "arena"
                  ? {
                      draftOrder: meta.draft_order ?? [],
                      drafts: meta.drafts ?? [],
                      votes: meta.votes ?? [],
                      scores: meta.scores,
                      winner: meta.winner,
                      usage: meta.usage,
                      events: [{ type: "arena_verdict", ...(meta as any) }],
                    }
                  : undefined,
              think:
                meta.mode === "chat+think"
                  ? {
                      provider: meta.provider ?? "",
                      traces: meta.think_traces ?? [],
                      summary: meta.thinking_summary ?? undefined,
                      elapsedMs: meta.think_time_ms ?? 0,
                      usage: meta.think_usage,
                      events: [{ type: "thinking_end", ...(meta as any) }],
                    }
                  : undefined,
            };
          })
        );
      })
      .catch(console.error);
  }, [activeId]);

  // Keyboard shortcuts: ⌘K new chat · `/` focus input · Esc stop
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setActiveId(null);
      }
      if (e.key === "/" && !(e.target as HTMLElement).matches("input,textarea")) {
        e.preventDefault();
        document.getElementById("composer-input")?.focus();
      }
      if (e.key === "Escape") stop();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function patchLast(fn: (m: ChatMsg) => ChatMsg) {
    setMsgs((m) => {
      const a = [...m];
      a[a.length - 1] = fn({ ...a[a.length - 1] });
      return a;
    });
  }

  async function send(text: string, search: boolean, regenerate = false, forceRematch = false) {
    if ((!text.trim() && files.length === 0 && !regenerate) || busy) return;
    setBusy(true);
    busyRef.current = true;
    const useArena = (arenaMode || forceRematch) && !regenerate;
    const useThink = thinkOn && !arenaMode && !agentMode && THINKABLE.includes(model);
    const specialMode = agentMode || deepMode || useArena;
    const fileIds = specialMode || regenerate ? [] : files.map((f) => f.id);
    setMsgs((m) => [
      ...m,
      { role: "user", content: text, author: wsId ? "you" : undefined },
      { role: "assistant", content: "" },
    ]);
    setFiles([]);
    const endpoint = agentMode
      ? "/agents/stream"
      : deepMode
        ? "/deepsearch/stream"
        : useArena
          ? "/agents/arena/stream"
          : "/chat/stream";
    const pushLog = (icon: string, line: string) =>
      patchLast((m) =>
        m.research
          ? { ...m, research: { ...m.research, log: [...m.research.log, { icon, text: line }].slice(-14) } }
          : m
      );
    let newId: string | null = null;
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await streamChat(
        {
          conversation_id: activeId,
          workspace_id: wsId,
          message: text,
          files: fileIds,
          search,
          plugins: pluginMode,
          regenerate,
          depth: deepMode ? "deep" : undefined,
          model,
          think: thinkOn,
          arena: useArena,
          arena_extra: arenaExtra,
          rematch: forceRematch || undefined,
        },
        (ev) => {
          if (ev.type === "meta") {
            if (ev.model) patchLast((m) => ({ ...m, model: ev.model }));
            if (ev.conversation_id && !activeId) {
              newId = ev.conversation_id;
              skipNextLoad.current = true; // keep the streamed messages; don't refetch
            }
          }
          // multi-agent progress
          if (ev.type === "plan" && ev.steps)
            patchLast((m) => ({
              ...m,
              steps: (ev.steps ?? []).map((s) => ({ agent: s.agent, task: s.task, status: "queued" as const })),
            }));
          if (ev.type === "step_start" && ev.i != null)
            patchLast((m) => ({
              ...m,
              steps: m.steps?.map((s, idx) => (idx === ev.i ? { ...s, status: "running" as const } : s)),
            }));
          if (ev.type === "step_done" && ev.i != null)
            patchLast((m) => ({
              ...m,
              steps: m.steps?.map((s, idx) =>
                idx === ev.i ? { ...s, status: "done" as const, preview: ev.preview } : s
              ),
            }));
          // deepsearch progress
          if (ev.type === "subtopics" && ev.subtopics)
            patchLast((m) => ({ ...m, research: { subtopics: ev.subtopics ?? [], log: [] } }));
          if (ev.type === "round_start") pushLog("🔁", `Research round ${ev.round} of ${ev.total}`);
          if (ev.type === "query_start" && ev.query) pushLog("🔍", ev.query);
          if (ev.type === "query_done" && ev.query) pushLog("✅", `${ev.query} — ${ev.sources ?? 0} sources`);
          if (ev.type === "reflect" && ev.note) pushLog("🧭", `Gap analysis: ${ev.note}`);
          if (ev.type === "round_done" && ev.sources != null) pushLog("📚", `${ev.sources} unique sources collected`);
          if (ev.type === "writing") pushLog("✍️", "Writing the report…");
          if (ev.type === "tools" && ev.calls) patchLast((m) => ({ ...m, tools: ev.calls }));
          // staged write actions no longer pop up in-chat — they wait in the Plugin Store inbox (/plugins)
          // ⚔️ arena: drafts, votes, winner
          if (ev.type === "topic" || ev.type.startsWith("draft_") || ev.type.startsWith("vote_"))
            patchLast((m) => ({
              ...m,
              arena: { draftOrder: [], drafts: [], votes: [], events: [...(m.arena?.events ?? []), ev as ArenaEvt] },
            }));
          if (ev.type === "arena_verdict")
            patchLast((m) => ({
              ...m,
              arena: {
                draftOrder: ev.draft_order ?? [],
                drafts: ev.drafts ?? [],
                votes: ev.votes ?? [],
                scores: ev.scores,
                winner: ev.winner,
                usage: ev.usage,
                events: [...(m.arena?.events ?? []), ev as ArenaEvt],
              },
            }));
          // 🧠 extended reasoning (grok-4 / grok-code-fast-1)
          if (ev.type === "thinking_start")
            patchLast((m) => ({ ...m, think: { provider: ev.provider ?? "", traces: [], elapsedMs: 0, events: [] } }));
          if (ev.type === "thinking_trace" && ev.trace)
            patchLast((m) =>
              m.think ? { ...m, think: { ...m.think, traces: [...m.think.traces, ev.trace!] } } : m
            );
          if (ev.type === "thinking")
            patchLast((m) =>
              m.think
                ? {
                    ...m,
                    think: {
                      ...m.think,
                      summary: ev.thinking?.summary ?? undefined,
                      elapsedMs: ev.think_time_ms ?? m.think.elapsedMs,
                      usage: ev.usage,
                      events: [...m.think.events, ev as ThinkEvt],
                    },
                  }
                : m
            );
          if (ev.type === "delta" && ev.text) patchLast((m) => ({ ...m, content: m.content + ev.text }));
          if (ev.type === "citations") patchLast((m) => ({ ...m, citations: ev.citations }));
          if (ev.type === "error") {
            if (ev.error_code === "plan_limit") {
              setBillingNote(ev.message ?? "⚔️ Arena needs Pro — upgrade to unlock more debates.");
              setBillingCta("upgrade");
            }
            setMsgs((m) => {
              const a = [...m];
              a[a.length - 1] = {
                role: "assistant",
                content: (ev.error_code === "plan_limit" ? "🔒 " : "⚠️ ") + (ev.message ?? "Something went wrong"),
              };
              return a;
            });
          }
        },
        endpoint,
        ac.signal
      );
      if (newId) setActiveId(newId);
      await refresh();
    } catch (e: any) {
      if (e?.name === "AbortError") {
        patchLast((m) => ({ ...m, content: m.content + "\n\n⏹ *Stopped by user*" }));
      } else {
        patchLast((m) => ({ ...m, content: "⚠️ " + (e.message ?? "Request failed") }));
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
      busyRef.current = false;
    }
  }

  /** ⚔️ Rematch: rerun the arena — drafters are shown this winner and asked to beat it. */
  async function rematch() {
    if (busy) return;
    const lastUser = [...msgs].reverse().find((m) => m.role === "user");
    if (!lastUser) return;
    await send(lastUser.content, false, false, true);
  }

  async function regenerate() {
    if (!activeId || busy) return;
    const lastUser = [...msgs].reverse().find((m) => m.role === "user");
    if (!lastUser) return;
    // Drop the trailing exchange locally; server replays it cleanly
    setMsgs((m) => {
      const a = [...m];
      while (a.length && a[a.length - 1].role !== "user") a.pop();
      a.pop();
      return a;
    });
    await send(lastUser.content, true, true);
  }

  async function uploadFile(f: File) {
    const fd = new FormData();
    fd.append("file", f);
    const saved = await apiFetch<FileChip>("/files", { method: "POST", body: fd });
    setFiles((p) => [...p, saved]);
  }

  async function handleVoice(blob: Blob) {
    if (busy) return;
    setBusy(true);
    busyRef.current = true;
    try {
      const fd = new FormData();
      fd.append("file", blob, "voice.webm");
      if (activeId) fd.append("conversation_id", activeId);
      const res = await apiFetch<any>("/voice/chat", { method: "POST", body: fd });
      if (!activeId) {
        skipNextLoad.current = true;
        setActiveId(res.conversation_id);
      }
      setMsgs((m) => [
        ...m,
        { role: "user", content: "🎙️ " + res.transcript },
        { role: "assistant", content: res.reply },
      ]);
      if (res.audio_b64) void new Audio("data:audio/mpeg;base64," + res.audio_b64).play();
      await refresh();
    } catch (e: any) {
      alert(e.message ?? "Voice request failed");
    } finally {
      setBusy(false);
      busyRef.current = false;
    }
  }

  function exportChat() {
    const title = convs.find((c) => c.id === activeId)?.title || "mood-conversation";
    const md: string[] = [`# ${title}`, "", `_Exported from Mood AI · ${new Date().toLocaleString()}_`, ""];
    for (const m of msgs) {
      md.push(m.role === "user" ? "## 🧑 You" : "## ✦ Mood", "", m.content, "");
    }
    const blob = new Blob([md.join("\n")], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = title.replace(/[^\w-]+/g, "-").slice(0, 60) + ".md";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const activeTitle = convs.find((c) => c.id === activeId)?.title;

  async function shareChat() {
    if (!activeId) return;
    try {
      const r = await apiFetch<{ token: string; path: string }>(`/conversations/${activeId}/share`, {
        method: "POST",
      });
      const url = `${window.location.origin}${r.path}`;
      (await copyText(url))
        ? setShareMsg("Link copied ✓")
        : setShareMsg(`Link ready — long-press to copy: ${url}`);
      setShared(true);
      setTimeout(() => setShareMsg(""), 2500);
    } catch (e: any) {
      setShareMsg("⚠️ " + (e.message ?? "Share failed"));
      setTimeout(() => setShareMsg(""), 2500);
    }
  }

  async function revokeShare() {
    if (!activeId || !confirm("Revoke the public link? Anyone with it will lose access.")) return;
    try {
      await apiFetch(`/conversations/${activeId}/share`, { method: "DELETE" });
      setShared(false);
    } catch (e: any) {
      alert(e.message ?? "Revoke failed");
    }
  }

  return (
    <AppShell title={activeTitle || "Mood Chat"}>
      {/* conversation toolbar — always visible; Share/Export need a live conversation */}
      <div className="border-b border-line px-3 sm:px-4 py-2 flex items-center gap-3 text-xs text-gray-500 shrink-0 compact-v">
        {/* 🏠 Ask | Imagine tab pair (Grok-mirror; Imagine → image studio) */}
        <div className="flex items-center gap-4 shrink-0 pr-1">
          <span className="flex flex-col items-center" aria-current="page">
            <span className="text-sm font-semibold text-white leading-tight">Ask</span>
            <span className="h-0.5 w-5 rounded bg-white mt-0.5" />
          </span>
          <button onClick={() => router.push("/images")} className="flex flex-col items-center group">
            <span className="text-sm font-medium text-gray-500 group-hover:text-gray-300 leading-tight transition">Imagine</span>
            <span className="h-0.5 w-5 rounded bg-transparent mt-0.5" />
          </button>
        </div>
        <span className="flex-1 truncate">{activeTitle || (wsId ? `👥 ${wsName || "Team"} — new chat` : "")}</span>
        {wsId && (
          <button
            onClick={() => {
              const next = !showTeam;
              setShowTeam(next);
              if (next)
                apiFetch<{ conversations: any[] }>(`/workspaces/${wsId}/conversations`)
                  .then((c) => setTeamConvs(c.conversations))
                  .catch(() => {});
            }}
            className="text-accent flex items-center gap-1 shrink-0"
            title="Team workspace conversations"
          >
            👥 {wsName || "team"} {showTeam ? "▴" : "▾"}
          </button>
        )}
        {(agentMode || deepMode || arenaMode) && (
          <span className="text-accent">
            {agentMode ? "🤖 agent mode" : deepMode ? "🔭 deep search" : "⚔️ arena"}
          </span>
        )}
        {shareMsg && <span className="text-green-400">{shareMsg}</span>}
        {msgs.length > 0 && (
          <>
            <button onClick={shareChat} className="flex items-center gap-1 hover:text-gray-300 transition" title="Create a public read-only link">
              <Share2 size={13} /> Share
            </button>
            {shared && (
              <button onClick={revokeShare} className="flex items-center gap-1 hover:text-red-400 transition" title="Revoke the public link">
                <Link2Off size={13} /> Revoke
              </button>
            )}
            <button onClick={exportChat} className="flex items-center gap-1 hover:text-gray-300 transition">
              <Download size={13} /> Export
            </button>
          </>
        )}
      </div>
      {showTeam && wsId && (
        <div className="border-b border-line bg-panel px-3 sm:px-4 py-2 shrink-0 max-h-48 overflow-y-auto scrollbar-thin">
          <p className="text-[11px] text-gray-500 mb-1.5">Shared with the team — anyone in this workspace can read &amp; continue these</p>
          {!teamConvs || teamConvs.length === 0 ? (
            <p className="text-xs text-gray-600 py-1">No team conversations yet — send a message to start one.</p>
          ) : (
            <div className="space-y-1">
              {teamConvs.map((c) => (
                <button
                  key={c.id}
                  onClick={() => {
                    setShowTeam(false);
                    setActiveId(c.id);
                  }}
                  className={`w-full text-left text-xs rounded-lg px-2.5 py-1.5 border transition flex items-center gap-2 ${
                    c.id === activeId ? "bg-accent/10 border-accent/40 text-accent" : "bg-white/5 border-line text-gray-300 hover:bg-white/10"
                  }`}
                >
                  <span className="flex-1 truncate">{c.title}</span>
                  <span className="text-[10px] text-gray-500 shrink-0">by {c.author}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      {billingNote && (
        <div className="border-b border-accent/30 bg-accent/10 px-3 sm:px-4 py-2 text-xs text-accent flex items-center gap-2 shrink-0">
          <span className="flex-1">{billingNote}</span>
          {billingCta === "upgrade" && (
            <button
              onClick={() => router.push("/settings")}
              className="rounded-lg bg-accent text-black font-semibold px-3 py-1 hover:brightness-110 transition shrink-0"
            >
              ✨ Upgrade to Pro
            </button>
          )}
          <button
            onClick={() => {
              setBillingNote("");
              setBillingCta("");
            }}
            className="text-accent/70 hover:text-accent shrink-0"
          >
            ✕
          </button>
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin px-3 sm:px-4 py-6 compact-v">
        <div className="max-w-3xl xl:max-w-4xl 2xl:max-w-5xl mx-auto space-y-6">
          {msgs.length === 0 && <EmptyState />}
          {msgs.map((m, i) => (
            <MessageBubble
              key={i}
              msg={m}
              onRegenerate={
                !busy && i === msgs.length - 1 && m.role === "assistant" && msgs.length >= 2
                  ? regenerate
                  : undefined
              }
              onRematch={
                !busy && i === msgs.length - 1 && m.role === "assistant" && m.arena ? rematch : undefined
              }
            />
          ))}
          <div ref={bottomRef} />
        </div>
      </div>
      {/* 🏠 Grok-style quick-launch chips — only on the clean empty home */}
      {msgs.length === 0 && (
        <div className="px-3 sm:px-4 pb-2 shrink-0">
          <div className="max-w-3xl xl:max-w-4xl 2xl:max-w-5xl mx-auto flex gap-2 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {([
              { Icon: Clapperboard, label: "Create Videos", onClick: () => router.push("/films") },
              { Icon: Brush, label: "Create design", onClick: () => router.push("/design") },
              { Icon: ImageIcon, label: "Edit image", onClick: () => router.push("/images") },
              { Icon: AudioLines, label: "Voice", onClick: () => router.push("/voice") },
              { Icon: Telescope, label: "Deep research", onClick: () => setDeepMode(true) },
            ] as const).map(({ Icon, label, onClick }) => (
              <button
                key={label}
                onClick={onClick}
                className="flex items-center gap-1.5 rounded-full bg-white/[0.06] border border-white/10 px-3.5 py-2 text-xs text-gray-300 hover:border-accent/40 hover:text-white transition whitespace-nowrap shrink-0"
              >
                <Icon size={13} className="text-gray-500" /> {label}
              </button>
            ))}
          </div>
        </div>
      )}
      {/* 🧠 model picker + thinking + ⚔️ arena controls (hidden while deepsearching — it has its own pipeline) */}
      {!deepMode && (
        <ModelPicker
          model={model}
          setModel={setModel}
          thinkOn={thinkOn}
          toggleThink={() => setThinkOn((v) => !v)}
          thinkSupported={arenaMode ? false : THINKABLE.includes(model)}
          arenaMode={arenaMode}
          toggleArena={() => {
            setArenaMode((v) => !v);
            setAgentModeState(false);
          }}
          arenaExtra={arenaExtra}
          setArenaExtra={setArenaExtra}
        />
      )}
      <Composer
        busy={busy}
        onStop={stop}
        voiceMode={voiceMode}
        setVoiceMode={setVoiceMode}
        agentMode={agentMode}
        setAgentMode={setAgentMode}
        deepMode={deepMode}
        setDeepMode={setDeepMode}
        model={model}
        arenaMode={arenaMode}
        thinkOn={thinkOn && THINKABLE.includes(model) && !arenaMode}
        pluginMode={pluginMode}
        setPluginMode={setPluginMode}
        files={files}
        onRemoveFile={(id) => setFiles((f) => f.filter((x) => x.id !== id))}
        onUpload={uploadFile}
        onSend={(t, s) => send(t, s, false)}
        onVoice={handleVoice}
      />
    </AppShell>
  );
}
