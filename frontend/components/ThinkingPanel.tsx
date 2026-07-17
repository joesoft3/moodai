"use client";

import { useState } from "react";
import { Brain, ChevronDown, ChevronRight, Timer } from "lucide-react";
import type { ThinkState } from "./MessageBubble";

/** 🧠 Extended-reasoning events from chat stream (grok-4 / grok-code-fast-1). */
export interface ThinkEvt {
  type: string;
  provider?: string;
  trace?: string;
  thinking?: { summary?: string | null };
  think_time_ms?: number;
  usage?: Record<string, { in: number; out: number }>;
}

/** Collapsible reasoning-trace panel shown above the final answer. */
export default function ThinkingPanel({ state, replayEvents }: { state: ThinkState; replayEvents?: any[] }) {
  const [open, setOpen] = useState(false);
  const events: any[] = replayEvents ?? state.events ?? [];
  const finalEvt = events.find((e) => e.type === "thinking") as ThinkEvt | undefined;

  const trace = state.traces.join("");
  const summary = finalEvt?.thinking?.summary ?? state.summary;
  const elapsedMs = finalEvt?.think_time_ms ?? state.elapsedMs;
  const seconds = elapsedMs ? (elapsedMs / 1000).toFixed(1) : null;
  const live = !finalEvt && !state.summary;
  const hasTrace = trace.trim().length > 0;

  return (
    <div className="mb-3 rounded-xl border border-purple-400/25 bg-purple-400/5 p-3 space-y-1.5">
      <button
        onClick={() => hasTrace && setOpen((o) => !o)}
        className={`flex items-center gap-1.5 text-xs font-medium text-purple-300 ${hasTrace ? "hover:text-purple-200" : "cursor-default"} transition`}
      >
        <Brain size={13} className={live ? "animate-pulse" : ""} />
        🧠 Reasoning{state.provider ? ` · ${state.provider}` : ""}
        {seconds && (
          <span className="text-gray-500 font-normal flex items-center gap-1">
            <Timer size={11} /> {seconds}s
          </span>
        )}
        {live && <span className="text-gray-500 font-normal">thinking…</span>}
        {hasTrace && (open ? <ChevronDown size={12} /> : <ChevronRight size={12} />)}
      </button>
      {summary && (
        <p className="text-[11px] text-gray-400 italic border-l-2 border-purple-400/30 pl-2">{summary}</p>
      )}
      {open && hasTrace && (
        <p className="text-[11px] text-gray-500 whitespace-pre-wrap max-h-48 overflow-y-auto scrollbar-thin border-t border-purple-400/15 pt-1.5">
          {trace}
        </p>
      )}
    </div>
  );
}
