"use client";

import { useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy, Download, RotateCcw, Square, Volume2 } from "lucide-react";
import { apiFetch } from "@/lib/api";
import ArenaPanel from "./ArenaPanel";
import ThinkingPanel from "./ThinkingPanel";

/** DeepSearch answers persist sources as a markdown tail ("- [n](url)") — recover them for the chips row. */
export function extractCitationUrls(content: string): string[] {
  const urls: string[] = [];
  const re = /^\s*-\s*\[\d+\]\((https?:\/\/[^)\s]+)\)/gm;
  let m: RegExpExecArray | null;
  while ((m = re.exec(content)) !== null) {
    if (!urls.includes(m[1])) urls.push(m[1]);
  }
  return urls;
}

export interface AgentStep {
  agent: string;
  task: string;
  status: "queued" | "running" | "done";
  preview?: string;
}

export interface ResearchProgress {
  subtopics: string[];
  log: { icon: string; text: string }[];
}

export interface ArenaState {
  draftOrder: string[];
  drafts: { provider: string; content: string; round: number }[];
  votes: { provider: string; ballot: { vote: string; rationale: string } | null; valid: boolean }[];
  scores?: Record<string, { accuracy?: number; clarity?: number }>;
  winner?: string;
  usage?: Record<string, { in: number; out: number }>;
  events: any[]; // live event log (replayed for persisted messages)
}

export interface ThinkState {
  provider: string;
  traces: string[]; // streaming trace deltas
  summary?: string; // final server summary (if the model produced one)
  elapsedMs: number;
  usage?: Record<string, { in: number; out: number }>;
  events: any[];
}

export interface ConfirmAction {
  id: string;
  name: string;
  args: Record<string, any>;
  status: "pending" | "approved" | "rejected" | "failed";
  note?: string;
}

/** 🎨🎬 In-chat creation (v1.9.7): image/video generated inline from the chat box. */
export interface ChatMedia {
  kind: "image" | "video";
  url?: string;
  prompt?: string;
  stored?: string;
  pending?: boolean; // media_start received, still generating
  stage?: string;    // scenes | compositing (video pipeline)
  done?: number;
  total?: number;
}

export interface ChatMsg {
  role: "user" | "assistant" | "system";
  content: string;
  author?: string; // team chats: who wrote this user message
  citations?: string[];
  steps?: AgentStep[];
  research?: ResearchProgress;
  model?: string;
  tools?: { name: string; ok: boolean }[];
  actions?: ConfirmAction[];
  arena?: ArenaState; // ⚔️ multi-model debate
  think?: ThinkState; // 🧠 extended reasoning trace
  media?: ChatMedia[]; // 🎨🎬 in-chat creations
}

const AGENT_ICON: Record<string, string> = { researcher: "🔍", coder: "⌨️", writer: "✍️", critic: "🧐" };

/** 🎨🎬 In-chat creation card: shimmer while generating → image frame or video player. */
function MediaBlock({ m }: { m: ChatMedia }) {
  const label =
    m.kind === "image"
      ? "Painting your image…"
      : m.stage === "compositing"
        ? "Compositing your reel…"
        : m.stage === "scenes" && m.total
          ? `Directing scenes (${m.done ?? 0}/${m.total})…`
          : "Directing your reel…";
  if (m.pending || !m.url) {
    return (
      <div className="mb-3 overflow-hidden rounded-2xl border border-line bg-base/60">
        <div className="aspect-video w-full animate-pulse bg-gradient-to-br from-white/5 via-white/10 to-white/5" />
        <p className="px-3.5 py-2.5 text-xs text-gray-400 flex items-center gap-2">
          <span className="inline-block h-3 w-3 animate-spin rounded-full border border-accent border-t-transparent" />
          {m.kind === "image" ? "🎨" : "🎬"} {label}
        </p>
      </div>
    );
  }
  return (
    <div className="mb-3 overflow-hidden rounded-2xl border border-line bg-base/60">
      {m.kind === "image" ? (
        <a href={m.url} target="_blank" rel="noreferrer" title="Open full-size">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={m.url} alt={m.prompt ?? "Generated image"} className="block w-full max-w-lg" />
        </a>
      ) : (
        <video src={m.url} controls playsInline preload="metadata" className="block w-full max-w-lg bg-black" />
      )}
      <div className="flex items-center gap-2 px-3.5 py-2 text-[11px] text-gray-500">
        <span className="truncate flex-1">
          {m.kind === "image" ? "🎨" : "🎬"} {m.prompt}
        </span>
        {m.stored === "r2" && <span className="shrink-0" title="Saved to your library">☁️</span>}
        <a
          href={m.url}
          target="_blank"
          rel="noreferrer"
          download
          title="Download"
          className="shrink-0 text-gray-500 hover:text-white transition"
        >
          <Download size={13} />
        </a>
      </div>
    </div>
  );
}

function ToolPills({ tools }: { tools: { name: string; ok: boolean }[] }) {
  return (
    <div className="mb-3 flex flex-wrap gap-1.5">
      {tools.map((t, i) => (
        <span
          key={i}
          className={`text-[11px] rounded-full border px-2.5 py-1 ${
            t.ok
              ? "bg-accent/10 border-accent/25 text-accent"
              : "bg-red-400/10 border-red-400/30 text-red-400"
          }`}
        >
          🧩 {t.name} {t.ok ? "✓" : "✗"}
        </span>
      ))}
    </div>
  );
}

function ResearchPanel({ r }: { r: ResearchProgress }) {
  return (
    <div className="mb-3 rounded-xl border border-line bg-base/60 p-3 space-y-2">
      <p className="text-xs font-medium text-gray-400">🔭 Deep research</p>
      {r.subtopics.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {r.subtopics.map((s, i) => (
            <span
              key={i}
              className="text-[11px] rounded-full bg-accent/10 border border-accent/25 text-accent px-2.5 py-1"
            >
              {s}
            </span>
          ))}
        </div>
      )}
      {r.log.length > 0 && (
        <div className="space-y-1 max-h-40 overflow-y-auto scrollbar-thin">
          {r.log.map((l, i) => (
            <p key={i} className="text-[11px] text-gray-500 leading-snug">
              {l.icon} {l.text}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function AgentSteps({ steps }: { steps: AgentStep[] }) {
  return (
    <div className="mb-3 rounded-xl border border-line bg-base/60 p-3 space-y-2">
      <p className="text-xs font-medium text-gray-400">🤖 Agent team</p>
      {steps.map((s, i) => (
        <div key={i} className="flex items-start gap-2 text-xs">
          <span className="shrink-0">{s.status === "done" ? "✅" : s.status === "running" ? "⏳" : "▫️"}</span>
          <div className="min-w-0">
            <span className="text-accent font-medium">
              {AGENT_ICON[s.agent] ?? "🤖"} {s.agent}
            </span>
            <span className="text-gray-400"> — {s.task}</span>
            {s.preview && s.status === "done" && <p className="text-gray-600 truncate">{s.preview}</p>}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Code block with a hover copy button (pro touch). */
function CodePre(props: any) {
  const ref = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative group/code">
      <pre ref={ref} {...props} />
      <button
        onClick={async () => {
          await navigator.clipboard.writeText(ref.current?.innerText ?? "");
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
        className="absolute top-2 right-2 text-[10px] bg-white/10 hover:bg-white/20 border border-line rounded-md px-2 py-1 opacity-0 group-hover/code:opacity-100 transition"
      >
        {copied ? "Copied ✓" : "Copy"}
      </button>
    </div>
  );
}

export default function MessageBubble({
  msg,
  onRegenerate,
  onRematch,
}: {
  msg: ChatMsg;
  onRegenerate?: () => void;
  /** ⚔️ arena messages: rerun the debate — drafters try to beat this winner. */
  onRematch?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [reading, setReading] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  async function copyMessage() {
    await navigator.clipboard.writeText(msg.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  async function readAloud() {
    if (reading) {
      audioRef.current?.pause();
      setReading(false);
      return;
    }
    try {
      setReading(true);
      const blob = await apiFetch<Blob>("/voice/tts", {
        method: "POST",
        body: JSON.stringify({ text: msg.content.slice(0, 3900) }),
      });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => setReading(false);
      audio.onerror = () => setReading(false);
      await audio.play();
    } catch (e: any) {
      setReading(false);
      alert(e.message ?? "Read-aloud unavailable (set OPENAI_API_KEY)");
    }
  }

  if (msg.role === "user") {
    return (
      <div className="flex flex-col items-end gap-0.5">
        {msg.author && <span className="text-[10px] text-gray-500 pr-1">🧑 {msg.author}</span>}
        <div className="bg-accent/20 border border-accent/30 rounded-2xl px-4 py-3 max-w-[85%] whitespace-pre-wrap [overflow-wrap:anywhere] text-sm">
          {msg.content}
        </div>
      </div>
    );
  }

  return (
    <div className="msg text-gray-200 leading-relaxed text-[15px]">
      {msg.research && <ResearchPanel r={msg.research} />}
      {msg.steps && msg.steps.length > 0 && <AgentSteps steps={msg.steps} />}
      {msg.think && <ThinkingPanel state={msg.think} replayEvents={msg.think.events} />}
      {msg.arena && <ArenaPanel state={msg.arena} replayEvents={msg.arena.events} />}
      {msg.tools && msg.tools.length > 0 && <ToolPills tools={msg.tools} />}
      {msg.media && msg.media.length > 0 && (
        <div className="space-y-3">
          {msg.media.map((m, i) => (
            <MediaBlock key={i} m={m} />
          ))}
        </div>
      )}
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ pre: CodePre as any }}>
        {msg.content || "…"}
      </ReactMarkdown>

      {(() => {
        const cites =
          msg.citations && msg.citations.length > 0 ? msg.citations : extractCitationUrls(msg.content);
        if (cites.length === 0) return null;
        return (
          <div className="mt-3 pt-2 border-t border-line">
            <p className="text-xs text-gray-500 font-medium mb-1.5">📚 Sources · {cites.length}</p>
            <div className="flex flex-wrap gap-1.5">
              {cites.map((c, i) => {
                let host = c;
                try {
                  host = new URL(c).hostname.replace(/^www\./, "");
                } catch { /* keep the raw url */ }
                return (
                  <a
                    key={i}
                    href={c}
                    target="_blank"
                    rel="noreferrer"
                    title={c}
                    className="inline-flex items-center gap-1.5 rounded-full border border-line bg-base/60 px-2.5 py-1 text-[11px] text-accent hover:border-accent/50 hover:bg-accent/10 transition"
                  >
                    <span className="grid h-4 w-4 place-items-center rounded-full bg-accent/15 text-[10px] font-bold">{i + 1}</span>
                    {host}
                  </a>
                );
              })}
            </div>
          </div>
        );
      })()}

      {/* action bar */}
      {msg.content.length > 0 && (
        <div className="mt-2 flex items-center gap-3 text-gray-600">
          <button onClick={copyMessage} title="Copy answer" className="hover:text-gray-300 transition">
            {copied ? <Check size={13} className="text-green-400" /> : <Copy size={13} />}
          </button>
          <button onClick={readAloud} title={reading ? "Stop reading" : "Read aloud"} className="hover:text-gray-300 transition">
            {reading ? <Square size={12} className="text-accent" /> : <Volume2 size={13} />}
          </button>
          {onRegenerate && (
            <button onClick={onRegenerate} title="Regenerate response" className="hover:text-gray-300 transition">
              <RotateCcw size={13} />
            </button>
          )}
          {onRematch && (
            <button onClick={onRematch} title="⚔️ Rematch — providers try to beat this answer" className="hover:text-gray-300 transition text-[12px]">
              ⚔️
            </button>
          )}
          {msg.model && <span className="text-[10px] ml-auto">{msg.model}</span>}
        </div>
      )}
    </div>
  );
}
