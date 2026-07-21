"use client";

import { Brain, Swords } from "lucide-react";

export interface ModelOption {
  id: string;
  label: string;
  icon: string;
  hint: string;
}

export const MODEL_OPTIONS: ModelOption[] = [
  { id: "auto", label: "Auto", icon: "🚀", hint: "best pick per message" },
  { id: "grok-3-mini", label: "Mini", icon: "💸", hint: "cheapest, quick answers" },
  { id: "grok-4-fast", label: "S1 Mood-4-Fast", icon: "⚡", hint: "newest gen · 2M ctx" },
  { id: "grok-4", label: "S1 Mood-4", icon: "👑", hint: "flagship · 🧠 reasoning" },
  { id: "grok-code-fast-1", label: "Code", icon: "💻", hint: "grok-code-fast-1 · 🧠 reasoning" },
];

const ARENA_EXTRAS = ["", "gemini-2.5-flash", "grok-code-fast-1"] as const;

interface Props {
  model: string;
  setModel: (m: string) => void;
  thinkOn: boolean;
  toggleThink: () => void;
  /** Whether the current model supports 🧠 extended reasoning. */
  thinkSupported: boolean;
  arenaMode: boolean;
  toggleArena: () => void;
  arenaExtra: string;
  setArenaExtra: (v: string) => void;
}

/** Compact model / thinking / arena control row above the composer. */
export default function ModelPicker({
  model,
  setModel,
  thinkOn,
  toggleThink,
  thinkSupported,
  arenaMode,
  toggleArena,
  arenaExtra,
  setArenaExtra,
}: Props) {
  return (
    <div className="border-t border-line bg-panel/60 backdrop-blur px-2 sm:px-3 pt-2 compact-v">
      <div className="max-w-3xl xl:max-w-4xl 2xl:max-w-5xl mx-auto flex items-center gap-1.5 sm:flex-wrap flex-nowrap overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className="flex items-center gap-1 rounded-full bg-base border border-line p-1 shrink-0">
          {MODEL_OPTIONS.map((o) => (
            <button
              key={o.id}
              onClick={() => setModel(o.id)}
              title={`${o.label} — ${o.hint}`}
              className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition flex items-center gap-1 ${
                model === o.id && !arenaMode
                  ? "bg-accent text-black"
                  : "text-gray-400 hover:text-white hover:bg-white/5"
              }`}
            >
              <span className="hide-xxs">{o.icon}</span> {o.label}
            </button>
          ))}
        </div>
        <button
          onClick={toggleThink}
          disabled={!thinkSupported || arenaMode}
          title={
            thinkSupported
              ? "Extended reasoning — shows a 🧠 thinking trace (slower)"
              : "Thinking needs S1 Mood-4, Auto, or S1 Code (not 4-fast, not arena)"
          }
          className={`rounded-full border px-2.5 py-1.5 text-[11px] font-medium transition flex items-center gap-1 shrink-0 ${
            thinkOn && thinkSupported && !arenaMode
              ? "bg-purple-400/15 border-purple-400/40 text-purple-300"
              : "border-line text-gray-500 hover:text-white disabled:opacity-35 disabled:cursor-not-allowed"
          }`}
        >
          <Brain size={12} /> Thinking
        </button>
        <button
          onClick={toggleArena}
          title="⚔️ arena — multiple AI providers draft in parallel, blind-vote, Grok-4 judges (premium)"
          className={`rounded-full border px-2.5 py-1.5 text-[11px] font-medium transition flex items-center gap-1 shrink-0 ${
            arenaMode
              ? "bg-accent/15 border-accent/40 text-accent"
              : "border-line text-gray-500 hover:text-white"
          }`}
        >
          <Swords size={12} /> Arena
        </button>
        {arenaMode && (
          <select
            value={arenaExtra}
            onChange={(e) => setArenaExtra(e.target.value)}
            title="Extra provider to add to the arena (needs its API key configured server-side)"
            className="rounded-full bg-base border border-line text-[11px] text-gray-400 px-2 py-1.5 outline-none focus:border-accent/50 shrink-0"
          >
            {ARENA_EXTRAS.map((v) => (
              <option key={v || "none"} value={v}>
                {v === "" ? "＋ 3 providers (default)" : `＋ ${v}`}
              </option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}
