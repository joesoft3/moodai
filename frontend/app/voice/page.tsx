"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FileAudio, Loader2, Mic, RotateCcw, Square, Volume2 } from "lucide-react";
import AppShell from "@/components/AppShell";
import { API, apiFetch, token } from "@/lib/api";
import { useConversations } from "@/lib/conversations";
import { useRecorder } from "@/lib/use-recorder";

type Phase = "idle" | "listening" | "thinking" | "speaking";
type ConnState = "connecting" | "live" | "offline";

const PHASE_LABEL: Record<Phase, string> = {
  idle: "Tap the orb to talk",
  listening: "Listening… tap to send",
  thinking: "Mood is thinking…",
  speaking: "Speaking… tap to interrupt",
};

interface Turn {
  user: string;
  assistant: string;
}

function wsUrl(): string {
  return `${API.replace(/^http/, "ws")}/voice/ws?token=${encodeURIComponent(token.get() ?? "")}`;
}

export default function VoicePage() {
  const router = useRouter();
  const { setActiveId, refresh } = useConversations();
  const [phase, setPhase] = useState<Phase>("idle");
  const [conn, setConn] = useState<ConnState>("connecting");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionConv, setSessionConv] = useState<string | null>(null);
  const [error, setError] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const connConvRef = useRef<string | null>(null);
  const queueRef = useRef<string[]>([]);       // data:audio b64 chunks waiting to play
  const playingRef = useRef<string | null>(null); // currently playing b64
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const seeingLiveOnce = useRef(false);
  // ---- media file analysis (songs, podcasts, voice notes, video clips)
  const VIDEO_EXTS = ["mp4", "mov", "webm", "mkv", "m4v"];
  const isVideoFile = (f: File | null) => !!f && VIDEO_EXTS.includes(f.name.split(".").pop()?.toLowerCase() ?? "");
  const [aFile, setAFile] = useState<File | null>(null);
  const [aPrompt, setAPrompt] = useState("");
  const [aBusy, setABusy] = useState(false);
  const [aErr, setAErr] = useState("");
  const [aResult, setAResult] = useState<{
    transcript: string;
    analysis: string;
    conversation_id: string | null;
    filename: string;
    frames?: number;
    video?: boolean;
  } | null>(null);

  async function analyzeMedia() {
    if (!aFile || aBusy) return;
    const video = isVideoFile(aFile);
    setABusy(true);
    setAErr("");
    setAResult(null);
    try {
      const fd = new FormData();
      fd.append("file", aFile);
      if (aPrompt.trim()) fd.append("prompt", aPrompt.trim());
      const res = await apiFetch<{
        transcript: string;
        analysis: string;
        conversation_id: string | null;
        filename: string;
        frames?: number;
      }>(video ? "/files/analyze-video" : "/files/analyze-audio", { method: "POST", body: fd });
      setAResult({ ...res, video });
      void refresh();
    } catch (e: any) {
      setAErr(e.message ?? (video ? "Video analysis failed" : "Audio analysis failed"));
    } finally {
      setABusy(false);
    }
  }

  function openAnalysisChat() {
    if (!aResult?.conversation_id) return;
    setActiveId(aResult.conversation_id);
    router.push("/chat");
  }

  // ------------------------------------------------------- playback queue
  function drainQueue() {
    if (playingRef.current || queueRef.current.length === 0) return;
    const b64 = queueRef.current.shift()!;
    playingRef.current = b64;
    const audio = new Audio("data:audio/mpeg;base64," + b64);
    audioRef.current = audio;
    audio.onended = () => {
      playingRef.current = null;
      if (queueRef.current.length === 0) setPhase((p) => (p === "speaking" ? "idle" : p));
      drainQueue();
    };
    setPhase("speaking");
    void audio.play().catch(() => {
      playingRef.current = null;
      drainQueue();
    });
  }

  function stopPlayback() {
    queueRef.current = [];
    audioRef.current?.pause();
    playingRef.current = null;
  }

  // ------------------------------------------------------- websocket session
  useEffect(() => {
    let ws: WebSocket | null = null;
    let cancelled = false;
    function connect() {
      if (!token.get()) return;
      setConn("connecting");
      ws = new WebSocket(wsUrl());
      wsRef.current = ws;
      ws.onmessage = (evt) => {
        let ev: any;
        try {
          ev = JSON.parse(evt.data);
        } catch {
          return;
        }
        switch (ev.type) {
          case "ready":
            setConn("live");
            seeingLiveOnce.current = true;
            break;
          case "transcript":
            setPhase("thinking");
            setTurns((t) => [...t, { user: ev.text as string, assistant: "" }]);
            break;
          case "delta":
            setTurns((t) => {
              const a = [...t];
              const last = { ...a[a.length - 1] };
              last.assistant += ev.text as string;
              a[a.length - 1] = last;
              return a;
            });
            break;
          case "audio":
            queueRef.current.push(ev.audio_b64 as string);
            drainQueue();
            break;
          case "turn_done":
            if (ev.conversation_id && !connConvRef.current) {
              connConvRef.current = ev.conversation_id as string;
              setSessionConv(ev.conversation_id as string);
              setActiveId(ev.conversation_id as string);
              void refresh();
            }
            setPhase((p) => (queueRef.current.length === 0 && !playingRef.current ? "idle" : p));
            break;
          case "interrupted":
            stopPlayback();
            setPhase("idle");
            break;
          case "error":
            setError(ev.message ?? "Voice error");
            setPhase((p) => (p === "thinking" ? "idle" : p));
            break;
        }
      };
      ws.onclose = () => {
        if (cancelled) return;
        setConn("offline");
        if (!seeingLiveOnce.current) {
          setError("Realtime voice unavailable — check the backend and OPENAI_API_KEY.");
        }
      };
      ws.onerror = () => ws?.close();
    }
    connect();
    return () => {
      cancelled = true;
      wsRef.current = null;
      ws?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ------------------------------------------------------- recorder
  const { start, stop } = useRecorder(
    () => {
      // turn end → ask the server to process the buffered audio
      wsRef.current?.send(JSON.stringify({ type: "end_turn", conversation_id: connConvRef.current }));
      setPhase("thinking");
    },
    (chunk) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(chunk);
    }
  );

  async function handleOrb() {
    setError("");
    if (phase === "idle") {
      if (conn !== "live") {
        setError(conn === "offline" ? "Realtime voice offline — reload to retry." : "Connecting…");
        return;
      }
      stopPlayback();
      try {
        await start();
        setPhase("listening");
      } catch {
        setError("Microphone access denied or unavailable.");
      }
    } else if (phase === "listening") {
      stop(); // triggers onStop → end_turn
    } else {
      // thinking / speaking → barge-in
      wsRef.current?.send(JSON.stringify({ type: "interrupt" }));
      stopPlayback();
      setPhase("idle");
    }
  }

  function reset() {
    wsRef.current?.send(JSON.stringify({ type: "interrupt" }));
    stopPlayback();
    setSessionConv(null);
    connConvRef.current = null;
    setTurns([]);
    setPhase("idle");
    setError("");
  }

  const orbColor =
    phase === "listening" ? "bg-red-400/90" : phase === "thinking" ? "bg-accent/60" : "bg-accent";

  return (
    <AppShell
      title="Voice"
      headerRight={
        sessionConv ? (
          <button onClick={reset} className="flex items-center gap-1 text-xs text-accent px-2 py-1">
            <RotateCcw size={12} /> New session
          </button>
        ) : undefined
      }
    >
      <div className="flex-1 min-h-0 flex flex-col items-center px-4 py-6 compact-v">
        <div className="shrink-0 flex flex-col items-center gap-4 sm:gap-6 py-2 sm:py-4 compact-v">
          <div className="relative orb-scale h-44 w-44 xs:h-52 xs:w-52 sm:h-56 sm:w-56 md:h-72 md:w-72 lg:h-80 lg:w-80">
            <div
              className={`absolute inset-0 rounded-full bg-accent/10 ${
                phase === "listening" || phase === "speaking" ? "orb-ring" : ""
              }`}
            />
            <div
              className={`absolute inset-6 rounded-full bg-accent/15 ${
                phase === "listening" ? "orb-ring orb-ring-fast" : phase === "speaking" ? "orb-ring" : ""
              }`}
            />
            <div
              className={`absolute inset-12 rounded-full bg-accent/20 ${phase === "thinking" ? "orb-ring orb-ring-fast" : ""}`}
            />
            <button
              onClick={handleOrb}
              className={`absolute inset-12 xs:inset-14 sm:inset-16 md:inset-20 lg:inset-24 rounded-full flex items-center justify-center text-black shadow-lg shadow-accent/20 transition-colors ${orbColor}`}
              aria-label={PHASE_LABEL[phase]}
            >
              {phase === "listening" || phase === "speaking" ? (
                <Square className="w-8 h-8 sm:w-10 sm:h-10" />
              ) : phase === "thinking" ? (
                <Loader2 className="w-8 h-8 sm:w-10 sm:h-10 animate-spin" />
              ) : (
                <Mic className="w-8 h-8 sm:w-10 sm:h-10" />
              )}
            </button>
          </div>
          <p className="text-sm text-gray-400">{PHASE_LABEL[phase]}</p>
          <p className="text-[11px] text-gray-600 -mt-2">
            {conn === "live" ? "⚡ realtime session · streaming replies · barge-in supported" : conn === "connecting" ? "connecting…" : "offline"}
          </p>
          {error && <p className="text-xs text-yellow-500 max-w-xs text-center">{error}</p>}
        </div>

        {/* 🎵 analyze an audio or video file (song, podcast, voice note, clip) */}
        <details className="w-full max-w-2xl rounded-2xl border border-line bg-panel/60 open:pb-3 compact-v">
          <summary className="cursor-pointer select-none px-4 py-2.5 text-xs text-gray-400 hover:text-gray-200 transition flex items-center gap-2">
            <FileAudio size={13} className="text-accent" />
            🎵 Analyze audio or video — lyrics, summaries, scene-by-scene, what song is this?
          </summary>
          <div className="px-4 pt-2 space-y-2.5">
            <div className="flex gap-2 flex-wrap">
              <label className="cursor-pointer rounded-lg bg-white/5 border border-line px-3 py-1.5 text-xs text-gray-300 hover:bg-white/10 transition">
                {aFile ? aFile.name : "Choose audio (mp3, wav…) or video (mp4, mov…)"}
                <input
                  type="file"
                  accept="audio/*,video/*,.mp3,.wav,.m4a,.ogg,.opus,.webm,.flac,.mp4,.mov,.mkv,.m4v"
                  className="hidden"
                  onChange={(e) => {
                    setAFile(e.target.files?.[0] ?? null);
                    setAResult(null);
                    setAErr("");
                  }}
                />
              </label>
              <input
                value={aPrompt}
                onChange={(e) => setAPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") analyzeMedia();
                }}
                placeholder={
                  isVideoFile(aFile)
                    ? "Optional: what happens in this video? / find the product shown…"
                    : "Optional: what song is this? / summarize this lecture…"
                }
                className="flex-1 min-w-[200px] rounded-lg bg-base border border-line px-3 py-1.5 text-xs outline-none focus:border-accent/60 placeholder-gray-600"
              />
              <button
                onClick={analyzeMedia}
                disabled={!aFile || aBusy}
                className="rounded-lg bg-accent text-black text-xs font-semibold px-3.5 py-1.5 hover:brightness-110 transition disabled:opacity-40 flex items-center gap-1.5"
              >
                {aBusy && <Loader2 size={12} className="animate-spin" />}
                {aBusy ? "Analyzing…" : isVideoFile(aFile) ? "Analyze video" : "Analyze"}
              </button>
            </div>
            {isVideoFile(aFile) && (
              <p className="text-[10px] text-gray-600">
                Video mode: samples frames for vision analysis + transcribes the audio track (up to ~12 min).
              </p>
            )}
            {aErr && <p className="text-xs text-yellow-500">{aErr}</p>}
            {aResult && (
              <div className="rounded-xl bg-base border border-line p-3 space-y-2">
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-gray-300 font-medium truncate">
                    ✅ {aResult.filename}
                    {aResult.video && typeof aResult.frames === "number" && (
                      <span className="text-gray-500 font-normal"> · {aResult.frames} frames sampled</span>
                    )}
                  </span>
                  <button onClick={openAnalysisChat} className="ml-auto text-accent hover:underline shrink-0">
                    Open in chat →
                  </button>
                </div>
                {aResult.transcript.trim() && (
                  <details>
                    <summary className="cursor-pointer text-[11px] text-gray-500 hover:text-gray-300">
                      Show transcript / lyrics ({aResult.transcript.split(/\s+/).filter(Boolean).length} words)
                    </summary>
                    <p className="mt-1.5 text-xs text-gray-400 whitespace-pre-wrap max-h-40 overflow-y-auto scrollbar-thin">
                      {aResult.transcript}
                    </p>
                  </details>
                )}
                <p className="text-sm text-gray-200 whitespace-pre-wrap [overflow-wrap:anywhere] border-t border-line pt-2">
                  {aResult.analysis}
                </p>
              </div>
            )}
          </div>
        </details>

        {/* live transcript */}
        <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin w-full max-w-2xl space-y-4 mt-2 compact-v">
          {turns.map((t, i) => (
            <div key={i} className="space-y-2">
              <div className="flex justify-end">
                <div className="bg-accent/20 border border-accent/30 rounded-2xl px-4 py-2.5 max-w-[85%] text-sm whitespace-pre-wrap">
                  🎙️ {t.user}
                </div>
              </div>
              <div className="flex items-start gap-2 text-sm text-gray-300">
                <Volume2 size={14} className="text-accent mt-1 shrink-0" />
                <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{t.assistant || "…"}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
