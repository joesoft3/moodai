"use client";

import { useEffect, useRef, useState } from "react";
import { Bot, Globe, Headphones, Mic, Paperclip, Puzzle, SendHorizontal, Square, Telescope, X } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useRecorder } from "@/lib/use-recorder";

export interface FileChip {
  id: string;
  filename: string;
  mime: string;
}

interface Props {
  busy: boolean;
  onStop: () => void;
  voiceMode: boolean;
  setVoiceMode: (v: boolean) => void;
  agentMode: boolean;
  setAgentMode: (v: boolean) => void;
  deepMode: boolean;
  setDeepMode: (v: boolean) => void;
  pluginMode: boolean;
  setPluginMode: (v: boolean) => void;
  /** Active generation model — drives the hint under the composer. */
  model?: string;
  /** ⚔️ arena / 🧠 thinking states for the hint line. */
  arenaMode?: boolean;
  thinkOn?: boolean;
  files: FileChip[];
  onRemoveFile: (id: string) => void;
  onUpload: (f: File) => Promise<void>;
  onSend: (text: string, search: boolean) => Promise<void>;
  onVoice: (blob: Blob) => Promise<void>;
  /** 🎨🎬 Home chips prefill the input without sending (nonce retriggers). */
  draft?: { text: string; nonce: number };
  /** 🏠 bare = rendered inside the Grok-style centered empty home: no border-t strip. */
  bare?: boolean;
}

export default function Composer({
  busy,
  onStop,
  voiceMode,
  setVoiceMode,
  agentMode,
  setAgentMode,
  deepMode,
  setDeepMode,
  pluginMode,
  setPluginMode,
  model = "auto",
  arenaMode = false,
  thinkOn = false,
  files,
  onRemoveFile,
  onUpload,
  onSend,
  onVoice,
  draft,
  bare = false,
}: Props) {
  const [input, setInput] = useState("");
  const [searchOn, setSearchOn] = useState(true);
  const fileRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const canSend = !busy && (input.trim().length > 0 || files.length > 0);

  // 🎨🎬 "Create image/video" home chips prefill the composer (never auto-send)
  useEffect(() => {
    if (!draft) return;
    setInput(draft.text);
    const t = inputRef.current;
    if (t) {
      t.focus();
      t.style.height = "auto";
      t.style.height = Math.min(t.scrollHeight, 160) + "px";
      t.setSelectionRange(t.value.length, t.value.length);
    }
  }, [draft]);

  async function submit() {
    if (!canSend) return;
    const text = input;
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "auto";
    await onSend(text, searchOn);
  }

  async function handleAudio(blob: Blob) {
    if (voiceMode) {
      await onVoice(blob);
      return;
    }
    // Dictation mode: transcribe into the input box
    try {
      const fd = new FormData();
      fd.append("file", blob, "dictation.webm");
      const res = await apiFetch<{ text: string }>("/voice/transcribe", { method: "POST", body: fd });
      setInput((i) => (i ? i + " " : "") + res.text);
    } catch (e: any) {
      alert(e.message ?? "Transcription failed");
    }
  }

  const { recording, start, stop } = useRecorder((blob) => void handleAudio(blob));

  async function toggleMic() {
    if (recording) stop();
    else {
      try {
        await start();
      } catch {
        alert("Microphone access denied or unavailable.");
      }
    }
  }

  function autoGrow(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    const t = e.target;
    t.style.height = "auto";
    t.style.height = Math.min(t.scrollHeight, 160) + "px";
  }

  return (
    <div className={bare ? "w-full" : "border-t border-line bg-panel/80 backdrop-blur px-2 sm:px-3 py-2 sm:py-3 compact-v"}>
      <div className="max-w-3xl xl:max-w-4xl 2xl:max-w-5xl mx-auto space-y-2">
        {files.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {files.map((f) => (
              <span
                key={f.id}
                className="flex items-center gap-1.5 text-xs bg-white/5 border border-line rounded-full px-3 py-1.5 text-gray-300 max-w-full"
              >
                <span className="truncate max-w-[180px]">{f.filename}</span>
                <button onClick={() => onRemoveFile(f.id)} className="text-gray-500 hover:text-red-400" aria-label="Remove file">
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="flex items-end gap-0.5 sm:gap-1 rounded-[1.6rem] border border-line bg-white/5 px-2 sm:px-3 py-1.5 shadow-[0_8px_30px_rgb(0_0_0/0.5)] focus-within:border-accent/60 focus-within:shadow-[0_8px_36px_-6px_rgb(var(--mood-accent)/0.35)] transition">
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.json,.png,.jpg,.jpeg,.webp,.gif"
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f) {
                try {
                  await onUpload(f);
                } catch (err: any) {
                  alert(err.message ?? "Upload failed");
                }
              }
              e.target.value = "";
            }}
          />
          <button
            onClick={() => fileRef.current?.click()}
            title="Attach file"
            className="composer-btn text-gray-400 hover:text-white transition"
          >
            <Paperclip size={18} />
          </button>
          <textarea
            ref={inputRef}
            id="composer-input"
            value={input}
            onChange={autoGrow}
            rows={1}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={
              agentMode
                ? "Give the agent team a goal…"
                : deepMode
                  ? "Ask a complex question — deep multi-round research…"
                  : arenaMode
                    ? "Pose a question — 3+ AI models will debate it, Grok-4 judges…"
                    : model === "grok-code-fast-1"
                      ? "Describe code to write / a bug to fix (🧠 toggle for reasoning)…"
                      : thinkOn
                        ? "Ask something worth deep reasoning (grok-4 🧠)…"
                        : "Ask Mood…"
            }
            className="flex-1 min-w-0 bg-transparent resize-none outline-none text-sm py-2.5 px-1 placeholder-gray-600 max-h-40"
          />
          <button
            onClick={() => setSearchOn(!searchOn)}
            title="Toggle live web search"
            className={`composer-btn transition ${searchOn ? "text-accent" : "text-gray-600 hover:text-white"}`}
          >
            <Globe size={18} />
          </button>
          <button
            onClick={() => setAgentMode(!agentMode)}
            title="Agent mode — planner, researcher, coder & writer agents team up on your goal"
            className={`composer-btn transition ${agentMode ? "text-accent" : "text-gray-600 hover:text-white"}`}
          >
            <Bot size={18} />
          </button>
          <button
            onClick={() => setDeepMode(!deepMode)}
            title="Deep search — multi-round agentic web research with full citations"
            className={`composer-btn transition max-[560px]:hidden ${deepMode ? "text-accent" : "text-gray-600 hover:text-white"}`}
          >
            <Telescope size={18} />
          </button>
          <button
            onClick={() => setPluginMode(!pluginMode)}
            title="Plugins — act on your connected apps (Gmail, Calendar, GitHub). Connect them in Settings."
            className={`composer-btn transition max-[560px]:hidden ${pluginMode ? "text-accent" : "text-gray-600 hover:text-white"}`}
          >
            <Puzzle size={18} />
          </button>
          <button
            onClick={() => setVoiceMode(!voiceMode)}
            title="Voice mode (talk & hear replies)"
            className={`composer-btn transition max-[560px]:hidden ${voiceMode ? "text-accent" : "text-gray-600 hover:text-white"}`}
          >
            <Headphones size={18} />
          </button>
          <button
            onClick={toggleMic}
            title={recording ? "Stop recording" : voiceMode ? "Talk" : "Dictate"}
            className={`composer-btn transition ${recording ? "text-red-400 animate-pulse" : "text-gray-400 hover:text-white"}`}
          >
            {recording ? <Square size={18} /> : <Mic size={18} />}
          </button>
          {busy ? (
            <button
              onClick={onStop}
              title="Stop generating"
              className="composer-btn rounded-xl bg-red-400/90 text-black hover:bg-red-400 transition"
              aria-label="Stop generating"
            >
              <Square size={16} />
            </button>
          ) : (
            <button
              onClick={submit}
              disabled={!canSend}
              className="composer-btn rounded-xl bg-accent text-black disabled:opacity-30 hover:brightness-110 transition"
              aria-label="Send"
            >
              <SendHorizontal size={18} />
            </button>
          )}
        </div>
        <p className="text-[11px] text-gray-600 text-center hidden sm:block">
          {arenaMode
            ? "⚔️ Arena: Grok-4 · GPT · Gemini draft in parallel, blind-vote each other, Grok-4 judges — premium, uses 3× tokens"
            : thinkOn && model !== "grok-4-fast"
              ? `🧠 ${model === "grok-code-fast-1" ? "S1 Code" : "S1 Mood-4"} extended reasoning — slower, deeper answers`
              : model === "grok-4-fast"
                ? "⚡ S1 Mood-4-Fast — newer generation with 2M context (no thinking mode)"
                : model === "grok-3-mini"
                  ? "💸 grok-3-mini — cheapest, great for quick questions"
                  : "Mood can make mistakes — verify important info. 🧠 thinking & ⚔️ arena available above"}
        </p>
      </div>
    </div>
  );
}
