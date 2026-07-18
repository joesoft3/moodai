"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Clapperboard, Download, Image as ImageIcon, Loader2, Sparkles, Wand2, X } from "lucide-react";
import AppShell from "@/components/AppShell";
import { apiFetch } from "@/lib/api";

interface ImgItem {
  id: string;
  url: string;
  prompt: string;
  pending?: boolean;
  meta?: {
    duration?: number;
    aspect_ratio?: string;
    quality?: string;
    style?: string;
    audio?: string;      // "none" | "voice" | "voice+ambience"
    script?: string;     // the AI voiceover actually spoken
    requestedAudio?: string;
  };
}

const STORE_KEY = "mood_images";
const VIDEO_STORE_KEY = "mood_videos";

const STYLES = [
  { id: "cinematic", label: "🎥 Cinematic" },
  { id: "photoreal", label: "📷 Photoreal" },
  { id: "product_ad", label: "💎 Product ad" },
  { id: "anime", label: "🌸 Anime" },
  { id: "documentary", label: "🌍 Documentary" },
  { id: "timelapse", label: "⏱ Timelapse" },
  { id: "retro_film", label: "📼 Retro film" },
];

const TEMPLATES = [
  { label: "💎 Product ad", style: "product_ad", aspect: "1:1", duration: 8,
    prompt: "A luxury perfume bottle rotating slowly on a black marble podium, mist swirling, gold accent light" },
  { label: "🎬 Cinematic hero shot", style: "cinematic", aspect: "16:9", duration: 8,
    prompt: "A lone astronaut walking across a windswept Mars ridge at golden hour, dust trailing behind" },
  { label: "📱 Social reel", style: "cinematic", aspect: "9:16", duration: 6,
    prompt: "Fresh coffee pouring into a ceramic cup in slow motion, cafe bokeh background, morning light" },
  { label: "🌸 Anime loop", style: "anime", aspect: "16:9", duration: 6,
    prompt: "A girl on a train watching cherry blossoms drift past the window at sunset" },
  { label: "🌍 Nature doc", style: "documentary", aspect: "16:9", duration: 10,
    prompt: "A snow leopard stalking across a Himalayan ridge in falling snow" },
  { label: "⏱ City timelapse", style: "timelapse", aspect: "16:9", duration: 8,
    prompt: "Accra skyline from day to night, traffic light trails, clouds racing" },
];

const STAGE_FLOW = [
  [0, "🎬 Storyboarding with director model…"],
  [8, "🧠 Compiling style + camera language…"],
  [20, "🎞 Rendering frames…"],
  [60, "✨ Upscaling & motion smoothing…"],
  [150, "📦 Finalizing (still normal — video is heavy)…"],
] as const;

const SOUND_STAGE_FLOW = [
  [0, "🎬 Storyboarding with director model…"],
  [8, "🧠 Compiling style + camera language…"],
  [20, "🎞 Rendering frames…"],
  [60, "🎙 Writing + recording the AI voiceover…"],
  [90, "🎚 Mixing voice, ambience & loudness polish…"],
  [150, "📦 Finalizing (still normal — video is heavy)…"],
] as const;

const VOICES: { v: string; label: string }[] = [
  { v: "alloy", label: "🎙 Alloy · neutral" },
  { v: "nova", label: "✨ Nova · warm fem" },
  { v: "shimmer", label: "🌟 Shimmer · bright fem" },
  { v: "echo", label: "🗣 Echo · smooth masc" },
  { v: "onyx", label: "🖤 Onyx · deep masc" },
  { v: "fable", label: "📖 Fable · storyteller" },
  { v: "sage", label: "🌿 Sage · calm" },
  { v: "ash", label: "🌫 Ash · soft masc" },
  { v: "coral", label: "🪸 Coral · upbeat fem" },
  { v: "verse", label: "🎬 Verse · trailer" },
];

function VideoPendingTile({ sound }: { sound?: boolean }) {
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, []);
  const flow = sound ? SOUND_STAGE_FLOW : STAGE_FLOW;
  const stage = [...flow].reverse().find(([t]) => secs >= t)?.[1] ?? flow[0][1];
  return (
    <div className="aspect-video rounded-xl border border-line bg-panel animate-pulse flex flex-col items-center justify-center gap-2 px-4">
      <Loader2 size={22} className="animate-spin text-accent" />
      <p className="text-[11px] text-gray-400 text-center">{stage}</p>
      <p className="text-[10px] text-gray-600">{secs}s elapsed · typical 1–5 min</p>
    </div>
  );
}

function ChipRow<T extends string | number>({
  label, value, options, onChange,
}: { label: string; value: T; options: { v: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-[11px] text-gray-500 w-16 shrink-0">{label}</span>
      {options.map((o) => (
        <button
          key={String(o.v)}
          onClick={() => onChange(o.v)}
          className={`text-[11px] rounded-full border px-2.5 py-1 transition ${
            value === o.v ? "bg-accent/15 border-accent/40 text-accent" : "bg-white/5 border-line text-gray-400 hover:text-gray-200"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function ImagesPage() {
  const [prompt, setPrompt] = useState("");
  const [mode, setMode] = useState<"image" | "video">("image");
  const [items, setItems] = useState<ImgItem[]>([]);
  const [videos, setVideos] = useState<ImgItem[]>([]);
  const [zoom, setZoom] = useState<ImgItem | null>(null);
  const [error, setError] = useState("");
  // video studio options
  const [duration, setDuration] = useState(8);
  const [aspect, setAspect] = useState<"16:9" | "9:16" | "1:1">("16:9");
  const [quality, setQuality] = useState<"720p" | "1080p">("720p");
  const [style, setStyle] = useState("cinematic");
  const [negative, setNegative] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  // cinema sound options
  const [audioMode, setAudioMode] = useState<"none" | "narration" | "cinema">("cinema");
  const [voiceId, setVoiceId] = useState("alloy");
  const [narration, setNarration] = useState("");
  const [info, setInfo] = useState("");
  const [enhancing, setEnhancing] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Restore previous generations (skip data: URLs — too large for localStorage)
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (raw) setItems(JSON.parse(raw));
      const vraw = localStorage.getItem(VIDEO_STORE_KEY);
      if (vraw) setVideos(JSON.parse(vraw));
    } catch {
      /* ignore */
    }
  }, []);

  function persist(next: ImgItem[]) {
    setItems(next);
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(next.filter((i) => i.url.startsWith("http")).slice(0, 24)));
    } catch {
      /* quota — non-fatal */
    }
  }

  function persistVideos(next: ImgItem[]) {
    setVideos(next);
    try {
      localStorage.setItem(VIDEO_STORE_KEY, JSON.stringify(next.slice(0, 12)));
    } catch {
      /* quota — non-fatal */
    }
  }

  async function generate() {
    const p = prompt.trim();
    if (!p) return;
    setPrompt("");
    setError("");
    const tmpId = "pending-" + Date.now();
    setItems((it) => [{ id: tmpId, url: "", prompt: p, pending: true }, ...it]);
    try {
      const res = await apiFetch<{ url: string }>("/chat/image", {
        method: "POST",
        body: JSON.stringify({ prompt: p }),
      });
      setItems((it) => {
        const next = it.map((i) => (i.id === tmpId ? { id: tmpId.replace("pending", "img"), url: res.url, prompt: p } : i));
        persist(next);
        return next;
      });
    } catch (e: any) {
      setItems((it) => it.filter((i) => i.id !== tmpId));
      setError(e.message ?? "Generation failed");
    }
  }

  async function generateVideo() {
    const p = prompt.trim();
    if (!p) return;
    setError("");
    setInfo("");
    const meta: ImgItem["meta"] = { duration, aspect_ratio: aspect, quality, style, requestedAudio: audioMode };
    const tmpId = "pending-" + Date.now();
    setVideos((it) => [{ id: tmpId, url: "", prompt: p, pending: true, meta }, ...it]);
    const ac = new AbortController();
    abortRef.current = ac;
    const to = setTimeout(() => ac.abort(), 6 * 60 * 1000);
    try {
      const res = await apiFetch<{ url: string; audio?: string; script?: string | null; note?: string | null }>("/media/videos", {
        method: "POST",
        body: JSON.stringify({
          prompt: p, duration, aspect_ratio: aspect, quality, style, negative_prompt: negative,
          audio: audioMode, voice: voiceId, narration: narration.trim(),
        }),
        signal: ac.signal,
      });
      setPrompt("");
      if (res.note) setInfo(`ℹ️ ${res.note}`);
      if (res.audio && res.audio !== "none") setInfo(`🔊 ${res.audio === "voice+ambience" ? "Voice + ambience" : "Voice"} soundtrack mixed — loudness-polished. 🎧`);
      const doneMeta: ImgItem["meta"] = { ...meta, audio: res.audio ?? "none", script: res.script ?? undefined };
      setVideos((it) => {
        const next = it.map((i) => (i.id === tmpId ? { id: tmpId.replace("pending", "vid"), url: res.url, prompt: p, meta: doneMeta } : i));
        persistVideos(next);
        return next;
      });
    } catch (e: any) {
      setVideos((it) => it.filter((i) => i.id !== tmpId));
      setError(e?.name === "AbortError" ? "Video generation timed out." : (e.message ?? "Video generation failed"));
    } finally {
      clearTimeout(to);
      abortRef.current = null;
    }
  }

  async function enhancePrompt() {
    const p = prompt.trim();
    if (!p || enhancing) return;
    setEnhancing(true);
    setError("");
    try {
      const res = await apiFetch<{ enhanced: string }>("/media/videos/enhance", {
        method: "POST",
        body: JSON.stringify({ prompt: p }),
      });
      setPrompt(res.enhanced);
    } catch (e: any) {
      setError(e.message ?? "Enhance failed");
    } finally {
      setEnhancing(false);
    }
  }

  function applyTemplate(t: (typeof TEMPLATES)[number]) {
    setPrompt(t.prompt);
    setStyle(t.style);
    setAspect(t.aspect as "16:9" | "9:16" | "1:1");
    setDuration(t.duration);
  }

  const busyVideo = abortRef.current !== null;

  return (
    <AppShell title="Media Lab">
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin px-4 py-6">
        <div className="max-w-5xl 2xl:max-w-7xl mx-auto space-y-6">
          {/* Mode toggle */}
          <div className="flex gap-2 text-xs">
            {(
              [
                { id: "image" as const, label: "🖼 Images", Icon: ImageIcon },
                { id: "video" as const, label: "🎬 Video Studio", Icon: Clapperboard },
              ] as const
            ).map((m) => (
              <button
                key={m.id}
                onClick={() => setMode(m.id)}
                className={`rounded-full border px-3 py-1.5 transition flex items-center gap-1.5 ${
                  mode === m.id
                    ? "bg-accent/15 border-accent/40 text-accent"
                    : "bg-white/5 border-line text-gray-400 hover:text-gray-200"
                }`}
              >
                <m.Icon size={13} /> {m.label}
              </button>
            ))}
          </div>

          {/* Video Studio pro panel */}
          {mode === "video" && (
            <div className="rounded-2xl border border-line bg-panel p-3 sm:p-4 space-y-3">
              <div className="flex gap-1.5 flex-wrap">
                {TEMPLATES.map((t) => (
                  <button
                    key={t.label}
                    onClick={() => applyTemplate(t)}
                    className="text-[11px] rounded-full bg-white/5 border border-line px-3 py-1.5 text-gray-300 hover:bg-white/10 hover:text-white transition"
                  >
                    {t.label}
                  </button>
                ))}
              </div>
              <ChipRow label="Duration" value={duration} onChange={setDuration}
                options={[5, 8, 10, 15].map((v) => ({ v, label: `${v}s` }))} />
              <ChipRow label="Aspect" value={aspect} onChange={setAspect}
                options={[{ v: "16:9", label: "▭ 16:9" }, { v: "9:16", label: "▯ 9:16" }, { v: "1:1", label: "◻ 1:1" }]} />
              <ChipRow label="Quality" value={quality} onChange={setQuality}
                options={[{ v: "720p", label: "720p" }, { v: "1080p", label: "1080p ✨" }]} />
              <ChipRow label="Style" value={style} onChange={setStyle}
                options={STYLES.map((s) => ({ v: s.id, label: s.label }))} />
              <ChipRow label="🔊 Sound" value={audioMode} onChange={setAudioMode}
                options={[
                  { v: "none" as const, label: "🔇 None" },
                  { v: "narration" as const, label: "🎙 AI voiceover" },
                  { v: "cinema" as const, label: "🎼 Voice + ambience" },
                ]} />
              {audioMode !== "none" && (
                <div className="rounded-xl bg-base border border-line p-3 space-y-2.5">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-[11px] text-gray-500 w-16 shrink-0">Voice</span>
                    <select
                      value={voiceId}
                      onChange={(e) => setVoiceId(e.target.value)}
                      className="rounded-lg bg-panel border border-line px-2 py-1 text-[11px] text-gray-300 outline-none focus:border-accent/60"
                    >
                      {VOICES.map((v) => (
                        <option key={v.v} value={v.v}>{v.label}</option>
                      ))}
                    </select>
                    <span className="text-[10px] text-gray-600 ml-auto">loudness-polished · EBU R128</span>
                  </div>
                  <textarea
                    value={narration}
                    onChange={(e) => setNarration(e.target.value)}
                    rows={2}
                    maxLength={600}
                    placeholder="Optional: write the exact voiceover… leave blank and the director model writes one sized to your clip."
                    className="w-full rounded-lg bg-panel border border-line px-2.5 py-1.5 text-[11px] outline-none focus:border-accent/60 placeholder-gray-600 resize-none"
                  />
                  <p className="text-[10px] text-gray-600">
                    🎧 Pure sound & voice: AI narration recorded in your chosen voice, mixed{" "}
                    {audioMode === "cinema" ? "over a soft ambient bed (and any sound the clip already has) " : ""}
                    by our ffmpeg mixer.
                  </p>
                </div>
              )}
              <button
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-300 transition"
              >
                <ChevronDown size={12} className={`transition-transform ${showAdvanced ? "rotate-180" : ""}`} />
                Advanced — negative prompt
              </button>
              {showAdvanced && (
                <input
                  value={negative}
                  onChange={(e) => setNegative(e.target.value)}
                  placeholder="What to avoid (e.g. people, text overlays, fast motion)…"
                  className="w-full rounded-xl bg-base border border-line px-3 py-2 text-xs outline-none focus:border-accent/60 placeholder-gray-600"
                />
              )}
            </div>
          )}

          {/* Prompt bar */}
          <div className="flex gap-2">
            <input
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") (mode === "video" ? generateVideo() : generate());
              }}
              placeholder={
                mode === "video"
                  ? "Describe your shot… or pick a template above, then ✨ Enhance"
                  : "A photorealistic red panda coding on a laptop, cinematic light…"
              }
              className="flex-1 rounded-2xl bg-base border border-line px-4 py-3 text-sm outline-none focus:border-accent/60 placeholder-gray-600"
            />
            {mode === "video" && (
              <button
                onClick={enhancePrompt}
                disabled={!prompt.trim() || enhancing}
                title="Enhance prompt with the director model"
                className="rounded-2xl border border-accent/40 bg-accent/10 text-accent px-3 sm:px-4 py-3 text-sm disabled:opacity-30 hover:bg-accent/20 transition flex items-center gap-1.5"
              >
                {enhancing ? <Loader2 size={16} className="animate-spin" /> : <Wand2 size={16} />}
                <span className="hidden sm:inline">Enhance</span>
              </button>
            )}
            <button
              onClick={() => (mode === "video" ? generateVideo() : generate())}
              disabled={!prompt.trim() || busyVideo}
              className="rounded-2xl bg-accent text-black font-semibold px-4 sm:px-6 py-3 text-sm disabled:opacity-30 hover:brightness-110 transition flex items-center gap-2"
            >
              <Sparkles size={16} /> <span className="hidden sm:inline">Generate</span>
            </button>
          </div>
          {error && <p className="text-sm text-red-400">{error}</p>}
          {info && <p className="text-sm text-accent">{info}</p>}

          {/* Gallery: 2 cols phone, 3 tablet, 4 desktop, 5 ultrawide */}
          {mode === "video" ? (
            videos.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {videos.map((v) =>
                  v.pending ? (
                    <VideoPendingTile key={v.id} sound={(v.meta?.requestedAudio ?? "none") !== "none"} />
                  ) : (
                    <div key={v.id} className="rounded-xl overflow-hidden border border-line bg-panel">
                      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
                      <video
                        src={v.url}
                        controls
                        playsInline
                        className={`w-full bg-black ${v.meta?.aspect_ratio === "9:16" ? "aspect-[9/16] max-h-[480px] mx-auto" : v.meta?.aspect_ratio === "1:1" ? "aspect-square" : "aspect-video"}`}
                      />
                      <div className="p-2 space-y-1.5">
                        <p className="text-[11px] text-gray-400 line-clamp-2">{v.prompt}</p>
                        {v.meta && (
                          <div className="flex gap-1.5 flex-wrap">
                            {[v.meta.aspect_ratio, v.meta.duration ? `${v.meta.duration}s` : "", v.meta.quality, v.meta.style?.replace("_", " ")]
                              .filter(Boolean)
                              .map((chip) => (
                                <span key={chip} className="text-[10px] rounded-full bg-white/5 border border-line px-2 py-0.5 text-gray-500">
                                  {chip}
                                </span>
                              ))}
                            {v.meta.audio && v.meta.audio !== "none" && (
                              <span className="text-[10px] rounded-full bg-accent/10 border border-accent/30 px-2 py-0.5 text-accent">
                                {v.meta.audio === "voice+ambience" ? "🎼 voice + ambience" : "🎙 AI voiceover"}
                              </span>
                            )}
                          </div>
                        )}
                        {v.meta?.script && (
                          <p className="text-[10px] text-gray-500 italic line-clamp-2 border-l-2 border-accent/30 pl-2">
                            “{v.meta.script}”
                          </p>
                        )}
                      </div>
                    </div>
                  )
                )}
              </div>
            ) : (
              <div className="text-center text-gray-600 pt-20 space-y-2">
                <div className="text-4xl">🎬</div>
                <p className="text-sm">Text-to-video with pure sound & voice: pick a template, tune duration / aspect / style, add an 🎙 AI voiceover or 🎼 full cinema mix, ✨ Enhance, generate.</p>
                <p className="text-[11px]">Generation can take 1–5 minutes (sound adds ~20s). Daily limits apply per plan.</p>
              </div>
            )
          ) : items.length > 0 ? (
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-2 sm:gap-3">
              {items.map((img) =>
                img.pending ? (
                  <div
                    key={img.id}
                    className="aspect-square rounded-xl border border-line bg-panel animate-pulse flex items-center justify-center"
                  >
                    <Loader2 size={22} className="animate-spin text-accent" />
                  </div>
                ) : (
                  <button
                    key={img.id}
                    onClick={() => setZoom(img)}
                    className="group relative aspect-square rounded-xl overflow-hidden border border-line bg-panel"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={img.url} alt={img.prompt} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
                    <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-2 text-left text-[11px] text-gray-300 line-clamp-2 opacity-0 group-hover:opacity-100 transition">
                      {img.prompt}
                    </span>
                  </button>
                )
              )}
            </div>
          ) : (
            <div className="text-center text-gray-600 pt-20 space-y-2">
              <div className="text-4xl">🖼️</div>
              <p className="text-sm">Describe anything — Mood draws it with Grok&rsquo;s image model.</p>
            </div>
          )}
        </div>
      </div>

      {/* Lightbox */}
      {zoom && (
        <div className="fixed inset-0 z-50 bg-black/85 backdrop-blur flex items-center justify-center p-4" onClick={() => setZoom(null)}>
          <div className="max-w-3xl w-full space-y-3" onClick={(e) => e.stopPropagation()}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={zoom.url} alt={zoom.prompt} className="w-full max-h-[75vh] object-contain rounded-xl" />
            <div className="flex items-center gap-3">
              <p className="flex-1 text-xs text-gray-400 line-clamp-2">{zoom.prompt}</p>
              <a
                href={zoom.url}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1.5 text-xs rounded-lg bg-white/10 hover:bg-white/20 px-3 py-2 transition"
              >
                <Download size={13} /> Original
              </a>
              <button onClick={() => setZoom(null)} className="flex items-center gap-1.5 text-xs rounded-lg bg-white/10 hover:bg-white/20 px-3 py-2 transition">
                <X size={13} /> Close
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
