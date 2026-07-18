"use client";

import { useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy, RotateCcw, Square, Volume2 } from "lucide-react";
import { apiFetch } from "@/lib/api";
import ArenaPanel from "./ArenaPanel";
import ThinkingPanel from "./ThinkingPanel";

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
}

const AGENT_ICON: Record<string, string> = { researcher: "🔍", coder: "⌨️", writer: "✍️", critic: "🧐" };

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
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ pre: CodePre as any }}>
        {msg.content || "…"}
      </ReactMarkdown>

      {msg.citations && msg.citations.length > 0 && (
        <div className="mt-3 pt-2 border-t border-line space-y-1">
          <p className="text-xs text-gray-500 font-medium">Sources</p>
          {msg.citations.map((c, i) => (
            <div key={i} className="text-xs">
              <a className="text-accent underline break-all" href={c} target="_blank" rel="noreferrer">
                [{i + 1}] {c}
              </a>
            </div>
          ))}
        </div>
      )}

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
