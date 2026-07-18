"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Clapperboard, Download, Image as ImageIcon, Loader2, Sparkles, Wand2, X } from "lucide-react";
import AppShell from "@/components/AppShell";
import { API, apiFetch, token } from "@/lib/api";

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
    scenes?: number;     // >1 → storyboard film
    subtitles?: boolean;
  };
}

interface Film {
  id: string;
  prompt: string;
  status: "rendering" | "done" | "failed";
  progress: number;
  scene_count: number;
  scene_seconds: number;
  aspect_ratio: string;
  quality: string;
  style: string;
  audio: string;
  voice: string;
  music: string;
  tempo: number;
  subtitles: boolean;
  url: string;
  script: string | null;
  note: string | null;
  scenes: { shot: string; narration: string }[];
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

const STORY_STAGE_FLOW = [
  [0, "🎬 Director model splitting your idea into scenes…"],
  [15, "🎞 Rendering scene clips one by one…"],
  [240, "🧵 Stitching the film (normalize → concat)…"],
  [300, "🎙 Recording every scene's voiceover…"],
  [330, "🎚 Mixing story, ambience & loudness polish…"],
  [390, "📦 Finalizing your film (still normal)…"],
] as const;

const MUSICS = [
  { v: "soft" as const, label: "🌙 Soft" },
  { v: "epic" as const, label: "🏔 Epic" },
  { v: "lofi" as const, label: "📻 Lofi" },
  { v: "tension" as const, label: "😰 Tension" },
];

const TEMPOS: { v: number; label: string }[] = [
  { v: 0.85, label: "🐢 Calm 0.85×" },
  { v: 1.0, label: "▶ Natural 1×" },
  { v: 1.15, label: "🐇 Punchy 1.15×" },
];

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

function VideoPendingTile({ sound, story }: { sound?: boolean; story?: boolean }) {
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, []);
  const flow = story ? STORY_STAGE_FLOW : sound ? SOUND_STAGE_FLOW : STAGE_FLOW;
  const stage = [...flow].reverse().find(([t]) => secs >= t)?.[1] ?? flow[0][1];
  return (
    <div className="aspect-video rounded-xl border border-line bg-panel animate-pulse flex flex-col items-center justify-center gap-2 px-4">
      <Loader2 size={22} className="animate-spin text-accent" />
      <p className="text-[11px] text-gray-400 text-center">{stage}</p>
      <p className="text-[10px] text-gray-600">{Math.floor(secs / 60)}m {secs % 60}s elapsed · {story ? "storyboards 3–12 min" : "typical 1–5 min"}</p>
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
  const [music, setMusic] = useState<"soft" | "epic" | "lofi" | "tension">("soft");
  const [tempo, setTempo] = useState(1.0);
  // ⭐ brand + 📷➡️🎬 image-to-video
  const [useBrand, setUseBrand] = useState(false);
  const [hasBrand, setHasBrand] = useState(false);
  const [i2vOpen, setI2vOpen] = useState(false);
  const [i2vFile, setI2vFile] = useState<File | null>(null);
  const [i2vPreview, setI2vPreview] = useState<string>("");
  const [i2vBusy, setI2vBusy] = useState(false);
  const [i2vFilm, setI2vFilm] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editFile, setEditFile] = useState<File | null>(null);
  const [editBusy, setEditBusy] = useState(false);
  const [edits, setEdits] = useState<{ id: string; instruction: string; status: string; url: string | null; note: string | null }[]>([]);

  // detect a saved Brand Kit once → reveal the ⭐ brand toggles
  const brandProbe = useRef(false);
  useEffect(() => {
    if (brandProbe.current) return;
    brandProbe.current = true;
    apiFetch<{ brand_name: string }>("/media/brand")
      .then((b) => setHasBrand(Boolean(b.brand_name)))
      .catch(() => {});
  }, []);

  // 🎬 storyboard options
  const [storyScenes, setStoryScenes] = useState(1);          // 1 = single shot
  const [storySeconds, setStorySeconds] = useState(6);        // per-scene seconds
  const [subtitles, setSubtitles] = useState(false);
  const [customScenes, setCustomScenes] = useState("");
  const [dialogue, setDialogue] = useState(false);
  const [voiceB, setVoiceB] = useState("onyx");
  const [voiceBusy, setVoiceBusy] = useState(false);
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

  // 🎬 Deep-link: /images?story=<filmId> loads a film back into the director's chair
  useEffect(() => {
    const fid = new URLSearchParams(window.location.search).get("story");
    if (!fid) return;
    (async () => {
      try {
        const f = await apiFetch<Film>(`/media/films/${fid}`);
        setMode("video");
        setStoryScenes(Math.min(Math.max(f.scene_count, 2), 4));
        setStorySeconds(Math.min(Math.max(f.scene_seconds, 5), 8));
        setAspect(f.aspect_ratio === "9:16" || f.aspect_ratio === "1:1" ? f.aspect_ratio : "16:9");
        setStyle(f.style || "cinematic");
        setAudioMode(f.audio === "voice" ? "narration" : f.audio === "voice+ambience" ? "cinema" : "none");
        setVoiceId(f.voice || "alloy");
        setMusic((["soft", "epic", "lofi", "tension"] as const).includes(f.music as any) ? (f.music as typeof music) : "soft");
        setTempo(f.tempo >= 0.7 && f.tempo <= 1.3 ? f.tempo : 1.0);
        setSubtitles(Boolean(f.subtitles));
        setCustomScenes(f.scenes.map((s) => (s.narration ? `${s.shot} || ${s.narration}` : s.shot)).join("\n"));
        setShowAdvanced(true);
        setPrompt(f.prompt);
        setInfo("🎬 Film loaded — tweak scenes / voice / music, then Generate to re-mix it.");
        window.history.replaceState(null, "", "/images");
      } catch {
        setError("Couldn't load that film for editing.");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  function finishTile(tmpId: string, p: string, meta: ImgItem["meta"], url: string, note?: string | null) {
    if (note) setInfo(`ℹ️ ${note}`);
    if (meta?.audio && meta.audio !== "none")
      setInfo(`🔊 ${meta.audio === "voice+ambience" ? "Voice + ambience" : "Voice"} soundtrack mixed — loudness-polished. 🎧${meta.subtitles ? " 💬 Subtitles burned in." : ""}`);
    setVideos((it) => {
      const next = it.map((i) => (i.id === tmpId ? { id: tmpId.replace("pending", "vid"), url, prompt: p, meta } : i));
      persistVideos(next);
      return next;
    });
  }

  /** Async storyboard: poll the film row until it leaves 'rendering'. */
  async function pollFilm(fid: string, ac: AbortController): Promise<Film> {
    for (;;) {
      if (ac.signal.aborted) throw new DOMException("aborted", "AbortError");
      const film = await apiFetch<Film>(`/media/films/${fid}`, { signal: ac.signal });
      if (film.status !== "rendering") return film;
      await new Promise((r) => setTimeout(r, 7000));
    }
  }

  async function generateVideo() {
    const p = prompt.trim();
    if (!p) return;
    setError("");
    setInfo("");
    const isStory = storyScenes > 1;
    const sceneLines = customScenes.split("\n").map((l) => l.trim()).filter(Boolean);
    const useCustom = isStory && sceneLines.length >= 2;
    const meta: ImgItem["meta"] = {
      duration: isStory ? storySeconds * (useCustom ? sceneLines.length : storyScenes) : duration,
      aspect_ratio: aspect, quality, style, requestedAudio: audioMode,
      scenes: isStory ? (useCustom ? sceneLines.length : storyScenes) : undefined,
    };
    const tmpId = "pending-" + Date.now();
    setVideos((it) => [{ id: tmpId, url: "", prompt: p, pending: true, meta }, ...it]);
    const ac = new AbortController();
    abortRef.current = ac;
    const timeoutMs = isStory ? 30 * 60 * 1000 : 6 * 60 * 1000; // films render async — be patient
    const to = setTimeout(() => ac.abort(), timeoutMs);
    try {
      if (isStory) {
        // 202: server queues the render → poll /media/films/{id}
        const queued = await apiFetch<{ film: Film }>("/media/videos/storyboard", {
          method: "POST",
          body: JSON.stringify({
            prompt: p, scenes: storyScenes, scene_seconds: storySeconds,
            aspect_ratio: aspect, quality, style, negative_prompt: negative,
            audio: audioMode, voice: voiceId, music, tempo, subtitles,
            dialogue: audioMode !== "none" && dialogue, voice_b: voiceB,
            custom_scenes: useCustom ? sceneLines : null,
            use_brand: useBrand,
          }),
          signal: ac.signal,
        });
        setPrompt("");
        setInfo("🎬 Filming in the background — track it here or on the Films page (safe to leave).");
        const film = await pollFilm(queued.film.id, ac);
        if (film.status === "failed") throw new Error(film.note ?? "Render failed");
        finishTile(tmpId, p, { ...meta, audio: film.audio, script: film.script ?? undefined, subtitles: film.subtitles }, film.url, film.note);
      } else {
        const res = await apiFetch<{ url: string; audio?: string; script?: string | null; note?: string | null }>("/media/videos", {
          method: "POST",
          body: JSON.stringify({
            prompt: p, duration, aspect_ratio: aspect, quality, style, negative_prompt: negative,
            audio: audioMode, voice: voiceId, narration: narration.trim(), music, tempo,
          }),
          signal: ac.signal,
        });
        setPrompt("");
        finishTile(tmpId, p, { ...meta, audio: res.audio ?? "none", script: res.script ?? undefined }, res.url, res.note);
      }
    } catch (e: any) {
      setVideos((it) => it.filter((i) => i.id !== tmpId));
      setError(e?.name === "AbortError" ? "Video generation timed out." : (e.message ?? "Video generation failed"));
    } finally {
      clearTimeout(to);
      abortRef.current = null;
    }
  }

  async function generateI2V() {
    const p = prompt.trim();
    if (!i2vFile || p.length < 3 || i2vBusy) return;
    if (i2vFilm) { return generateI2VFilm(); }
    setI2vBusy(true);
    setError("");
    const fd = new FormData();
    fd.append("file", i2vFile);
    fd.append("instruction", p);
    fd.append("duration", String(duration));
    fd.append("aspect_ratio", aspect);
    fd.append("quality", quality);
    fd.append("style", style);
    const tmpId = "pending-" + Date.now();
    setVideos((it) => [{ id: tmpId, url: "", prompt: `📷 ${p}`, pending: true, meta: { duration, aspect_ratio: aspect, quality, style } }, ...it]);
    try {
      const res = await apiFetch<{ video_url: string; image_used: boolean; note: string | null }>("/media/videos/i2v", {
        method: "POST",
        body: fd,
      });
      if (res.note) setInfo(`ℹ️ ${res.note}`);
      else setInfo("📷➡️🎬 Your image came alive — reference frame animated.");
      setPrompt("");
      setI2vFile(null);
      setI2vPreview("");
      finishTile(tmpId, `📷 ${p}`, { duration, aspect_ratio: aspect, quality, style, audio: "none" } as ImgItem["meta"], res.video_url);
    } catch (e: any) {
      setVideos((it) => it.filter((i) => i.id !== tmpId));
      setError(e.message ?? "Image-to-video failed");
    } finally {
      setI2vBusy(false);
    }
  }

  async function generateI2VFilm() {
    const p = prompt.trim();
    if (!i2vFile || p.length < 3 || i2vBusy) return;
    setI2vBusy(true);
    setError("");
    const fd = new FormData();
    fd.append("file", i2vFile);
    fd.append("prompt", p);
    fd.append("scenes", String(Math.max(2, storyScenes)));
    fd.append("scene_seconds", String(storySeconds));
    fd.append("aspect_ratio", aspect);
    fd.append("quality", quality);
    fd.append("style", style);
    fd.append("audio", audioMode);
    fd.append("voice", voiceId);
    fd.append("music", music);
    fd.append("tempo", String(tempo));
    fd.append("subtitles", subtitles ? "true" : "false");
    fd.append("use_brand", useBrand ? "true" : "false");
    const tmpId = "pending-" + Date.now();
    setVideos((it) => [{ id: tmpId, url: "", prompt: `📷🎞 ${p}`, pending: true, meta: { duration: storySeconds * Math.max(2, storyScenes), aspect_ratio: aspect, quality, style } }, ...it]);
    try {
      const queued = await apiFetch<{ film: Film }>("/media/videos/storyboard-i2v", { method: "POST", body: fd });
      setInfo("📷➡️🎬 Your photo opens the film — rendering scenes in the background…");
      setPrompt("");
      setI2vFile(null);
      setI2vPreview("");
      setI2vFilm(false);
      const film = await pollFilm(queued.film.id, new AbortController());
      if (film.status === "failed") throw new Error(film.note ?? "Render failed");
      finishTile(tmpId, `📷🎞 ${p}`, { duration: film.scene_count * film.scene_seconds, aspect_ratio: aspect, quality, style, audio: film.audio, scenes: film.scene_count } as ImgItem["meta"], film.url, film.note);
    } catch (e: any) {
      setVideos((it) => it.filter((i) => i.id !== tmpId));
      setError(e.message ?? "Film-from-image failed");
    } finally {
      setI2vBusy(false);
    }
  }

  async function pollEdit(eid: string) {
    for (let i = 0; i < 60; i++) {
      const e = await apiFetch<any>(`/media/edits/${eid}`);
      setEdits((es) => es.map((x) => (x.id === eid ? { ...x, status: e.status, url: e.url, note: e.note } : x)));
      if (e.status !== "rendering") return e;
      await new Promise((r) => setTimeout(r, 5000));
    }
    return null;
  }

  async function runEdit() {
    const p = prompt.trim();
    if (!editFile || p.length < 3 || editBusy) return;
    setEditBusy(true);
    setError("");
    const fd = new FormData();
    fd.append("file", editFile);
    fd.append("instruction", p);
    fd.append("use_brand", useBrand ? "true" : "false");
    try {
      const res = await apiFetch<{ edit: any }>("/media/edits", { method: "POST", body: fd });
      setEdits((es) => [{ ...res.edit }, ...es.slice(0, 9)]);
      setPrompt("");
      setInfo("✂️ Editing in the background — trimming, reframing, brand-stamping as asked…");
      const done = await pollEdit(res.edit.id);
      if (done?.status === "done" && done.url) setInfo("✨ Edit ready — play or download it below!");
      else if (done?.status === "failed") setError(done.note ?? "Edit failed");
    } catch (e: any) {
      setError(e.message ?? "Edit failed");
    } finally {
      setEditBusy(false);
    }
  }

  async function previewVoice() {
    if (voiceBusy) return;
    setVoiceBusy(true);
    setError("");
    try {
      const pretty = VOICES.find((v) => v.v === voiceId)?.label.split("·")[0].replace(/[^\w ]/g, "").trim() || voiceId;
      const res = await fetch(`${API}/voice/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token.get() ?? ""}` },
        body: JSON.stringify({ text: `Hey — I'm ${pretty}, your narrator. Let's make this shot sing.`, voice: voiceId }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Voice preview failed (${res.status})`);
      const url = URL.createObjectURL(await res.blob());
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      await audio.play();
    } catch (e: any) {
      setError(e.message ?? "Voice preview failed");
    } finally {
      setVoiceBusy(false);
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
          {/* 📷➡️🎬 Image → Video */}
          <section className="rounded-xl border border-line bg-white/5 overflow-hidden">
            <button onClick={() => setI2vOpen((o) => !o)} className="touch-manipulation w-full flex items-center gap-2 px-4 py-3 text-left">
              <span className="text-base">📷➡️🎬</span>
              <span className="text-sm font-semibold text-gray-100">Image → Video</span>
              <span className="text-xs text-gray-500">upload a photo, tell it what to do</span>
              <ChevronDown size={15} className={`ml-auto text-gray-500 transition-transform ${i2vOpen ? "rotate-180" : ""}`} />
            </button>
            {i2vOpen && (
              <div className="px-4 pb-4 pt-3 border-t border-line space-y-3">
                <div className="flex items-start gap-3">
                  <label className="touch-manipulation relative flex h-24 w-24 shrink-0 cursor-pointer items-center justify-center rounded-xl border border-dashed border-line bg-white/5 overflow-hidden hover:border-accent/50 transition">
                    {i2vPreview ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={i2vPreview} alt="reference" className="h-full w-full object-cover" />
                    ) : (
                      <span className="text-center text-[10px] text-gray-500 px-2">📷<br />Tap to upload<br />PNG · JPG · WebP · ≤8MB</span>
                    )}
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0] ?? null;
                        setI2vFile(f);
                        if (i2vPreview) URL.revokeObjectURL(i2vPreview);
                        setI2vPreview(f ? URL.createObjectURL(f) : "");
                      }}
                    />
                  </label>
                  <div className="flex-1 min-w-0 space-y-2">
                    <p className="text-[11px] text-gray-400">
                      Write your instruction in the prompt box below — e.g. <em>"make the model walk forward, camera slowly pushes in"</em> — then hit <b>🎬 Animate image</b>.
                    </p>
                    <button
                      onClick={generateI2V}
                      disabled={!i2vFile || prompt.trim().length < 3 || i2vBusy}
                      className="touch-manipulation flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-xs font-semibold text-[#0b0f14] disabled:opacity-40 hover:brightness-110 transition"
                    >
                      {i2vBusy ? <Loader2 size={13} className="animate-spin" /> : "🎬"} Animate image
                    </button>
                    <label className="flex items-center gap-2 text-[11px] text-gray-400 cursor-pointer select-none w-fit">
                      <input type="checkbox" checked={i2vFilm} onChange={(e) => setI2vFilm(e.target.checked)} className="accent-[#7c9bff]" />
                      🎞 Make it a film — my photo opens scene 1, the director continues the story
                    </label>
                    {i2vFilm && (
                      <p className="text-[10px] text-gray-600">
                        Uses your scene/audio settings below ({Math.max(2, storyScenes)} scenes × {storySeconds}s)
                      </p>
                    )}
                  </div>
                </div>
              </div>
            )}
          </section>
          {/* ✂️ Auto-Edit */}
          <section className="rounded-xl border border-line bg-white/5 overflow-hidden">
            <button onClick={() => setEditOpen((o) => !o)} className="touch-manipulation w-full flex items-center gap-2 px-4 py-3 text-left">
              <span className="text-base">✂️</span>
              <span className="text-sm font-semibold text-gray-100">Auto-Edit Video</span>
              <span className="text-xs text-gray-500">upload a clip, tell the editor what to do</span>
              <ChevronDown size={15} className={`ml-auto text-gray-500 transition-transform ${editOpen ? "rotate-180" : ""}`} />
            </button>
            {editOpen && (
              <div className="px-4 pb-4 pt-3 border-t border-line space-y-3">
                <div className="flex flex-wrap gap-1.5">
                  {["Make it vertical for TikTok + subtitles", "Cut the first 3 seconds, add lofi music",
                    "Black & white, slower, my logo on it", "Speed it up 1.5x, mute the audio"].map((ex) => (
                    <button key={ex} onClick={() => setPrompt(ex)}
                      className="touch-manipulation rounded-full border border-line px-2.5 py-1 text-[10px] text-gray-400 hover:border-accent/50 transition">{ex}</button>
                  ))}
                </div>
                <div className="flex items-start gap-3">
                  <label className="touch-manipulation relative flex h-16 w-28 shrink-0 cursor-pointer items-center justify-center rounded-xl border border-dashed border-line bg-white/5 overflow-hidden hover:border-accent/50 transition">
                    <span className="text-center text-[10px] text-gray-500 px-1">
                      {editFile ? `🎞 ${editFile.name.slice(0, 14)}…` : <>📹<br />Upload clip<br />MP4 · MOV · ≤150MB</>}
                    </span>
                    <input type="file" accept="video/mp4,video/quicktime,video/webm,video/x-msvideo" className="hidden"
                      onChange={(e) => setEditFile(e.target.files?.[0] ?? null)} />
                  </label>
                  <div className="flex-1 min-w-0 space-y-2">
                    <p className="text-[11px] text-gray-400">
                      Describe the edit in the prompt box — trim, reframe to any aspect, subtitles, speed, color grade, music bed, logo watermark.
                    </p>
                    <div className="flex items-center gap-3">
                      <button onClick={runEdit} disabled={!editFile || prompt.trim().length < 3 || editBusy}
                        className="touch-manipulation flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-xs font-semibold text-[#0b0f14] disabled:opacity-40 hover:brightness-110 transition">
                        {editBusy ? <Loader2 size={13} className="animate-spin" /> : "✂️"} Edit my video
                      </button>
                      {hasBrand && (
                        <label className="flex items-center gap-1.5 text-[11px] text-gray-400 cursor-pointer select-none">
                          <input type="checkbox" checked={useBrand} onChange={(e) => setUseBrand(e.target.checked)} className="accent-amber-400" />
                          ⭐ my logo
                        </label>
                      )}
                    </div>
                  </div>
                </div>
                {edits.length > 0 && (
                  <div className="space-y-2 pt-1">
                    {edits.map((e) => (
                      <div key={e.id} className="flex items-center gap-3 rounded-lg border border-line px-3 py-2">
                        <span className="text-base">{e.status === "done" ? "✅" : e.status === "failed" ? "⚠️" : "⏳"}</span>
                        <div className="flex-1 min-w-0">
                          <p className="truncate text-[11px] text-gray-300">{e.instruction}</p>
                          {e.note && e.status === "done" && <p className="truncate text-[10px] text-gray-600">{e.note}</p>}
                        </div>
                        {e.status === "done" && e.url && (
                          <a href={e.url} target="_blank" rel="noreferrer" download
                            className="touch-manipulation rounded-lg bg-accent/15 border border-accent/40 px-2.5 py-1.5 text-[10px] font-semibold text-accent hover:bg-accent/25 transition">
                            ▶ Watch / ⬇ Save
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>
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
              <ChipRow label="🎬 Scenes" value={storyScenes} onChange={setStoryScenes}
                options={[1, 2, 3, 4].map((v) => ({ v, label: v === 1 ? "Single shot" : `${v}-scene film` }))} />
              {storyScenes > 1 && (
                <ChipRow label="Per scene" value={storySeconds} onChange={setStorySeconds}
                  options={[5, 6, 8].map((v) => ({ v, label: `${v}s each` }))} />
              )}
              {storyScenes === 1 && (
                <ChipRow label="Duration" value={duration} onChange={setDuration}
                  options={[5, 8, 10, 15].map((v) => ({ v, label: `${v}s` }))} />
              )}
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
              {audioMode === "cinema" && (
                <ChipRow label="🎼 Music" value={music} onChange={setMusic} options={MUSICS} />
              )}
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
                    <button
                      onClick={previewVoice}
                      disabled={voiceBusy}
                      title="Hear this voice (10-sec sample)"
                      className="rounded-lg border border-accent/40 bg-accent/10 text-accent px-2 py-1 text-[11px] hover:bg-accent/20 transition disabled:opacity-40 flex items-center gap-1"
                    >
                      {voiceBusy ? <Loader2 size={11} className="animate-spin" /> : "▶"} Preview
                    </button>
                    <span className="text-[10px] text-gray-600 ml-auto">loudness-polished · EBU R128</span>
                  </div>
                  <ChipRow label="⏱ Tempo" value={tempo} onChange={setTempo} options={TEMPOS} />
                  {storyScenes > 1 && (
                    <div className="flex items-center gap-2 flex-wrap">
                      <label className="flex items-center gap-2 text-[11px] text-gray-400 cursor-pointer select-none">
                        <input
                          type="checkbox"
                          checked={dialogue}
                          onChange={(e) => setDialogue(e.target.checked)}
                          className="accent-[#7c9bff]"
                        />
                        👥 Dialogue film — two narrators trade lines
                      </label>
                      {dialogue && (
                        <span className="flex items-center gap-1.5">
                          <span className="text-[10px] text-gray-600">Voice B:</span>
                          <select
                            value={voiceB}
                            onChange={(e) => setVoiceB(e.target.value)}
                            className="rounded-lg bg-panel border border-line px-2 py-1 text-[11px] text-gray-300 outline-none focus:border-accent/60"
                          >
                            {VOICES.map((v) => (
                              <option key={v.v} value={v.v}>{v.label}</option>
                            ))}
                          </select>
                        </span>
                      )}
                    </div>
                  )}
                  {hasBrand && storyScenes > 1 && (
                    <label className="flex items-center gap-2 text-[11px] text-gray-400 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={useBrand}
                        onChange={(e) => setUseBrand(e.target.checked)}
                        className="accent-amber-400"
                      />
                      ⭐ Film in my brand — identity colors into scenes, logo stamped on the poster
                    </label>
                  )}
                  {storyScenes === 1 ? (
                    <textarea
                      value={narration}
                      onChange={(e) => setNarration(e.target.value)}
                      rows={2}
                      maxLength={600}
                      placeholder="Optional: write the exact voiceover… leave blank and the director model writes one sized to your clip."
                      className="w-full rounded-lg bg-panel border border-line px-2.5 py-1.5 text-[11px] outline-none focus:border-accent/60 placeholder-gray-600 resize-none"
                    />
                  ) : (
                    <p className="text-[10px] text-gray-600">
                      🎬 Each scene gets its own voiceover line — written by the director model, or from your custom
                      scenes' <code className="text-gray-500">|| narration</code> halves (Advanced).
                    </p>
                  )}
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
                Advanced — negative prompt{storyScenes > 1 ? ", subtitles, custom scenes" : ""}
              </button>
              {showAdvanced && (
                <div className="space-y-2">
                  <input
                    value={negative}
                    onChange={(e) => setNegative(e.target.value)}
                    placeholder="What to avoid (e.g. people, text overlays, fast motion)…"
                    className="w-full rounded-xl bg-base border border-line px-3 py-2 text-xs outline-none focus:border-accent/60 placeholder-gray-600"
                  />
                  {storyScenes > 1 && (
                    <>
                      <label className="flex items-center gap-2 text-[11px] text-gray-400 cursor-pointer select-none">
                        <input
                          type="checkbox"
                          checked={subtitles}
                          onChange={(e) => setSubtitles(e.target.checked)}
                          className="accent-[#7c9bff]"
                        />
                        💬 Burn narration in as subtitles
                      </label>
                      <textarea
                        value={customScenes}
                        onChange={(e) => setCustomScenes(e.target.value)}
                        rows={3}
                        placeholder={"Optional — direct the scenes yourself, one per line:\nshot description || optional narration line\n(written scenes override the AI split when 2+ lines given)"}
                        className="w-full rounded-xl bg-base border border-line px-3 py-2 text-xs outline-none focus:border-accent/60 placeholder-gray-600 resize-none"
                      />
                    </>
                  )}
                </div>
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
                    <VideoPendingTile key={v.id} sound={(v.meta?.requestedAudio ?? "none") !== "none"} story={(v.meta?.scenes ?? 1) > 1} />
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
                            {(v.meta.scenes ?? 1) > 1 && (
                              <span className="text-[10px] rounded-full bg-white/5 border border-line px-2 py-0.5 text-gray-400">
                                🎬 {v.meta.scenes}-scene film
                              </span>
                            )}
                            {v.meta.subtitles && (
                              <span className="text-[10px] rounded-full bg-white/5 border border-line px-2 py-0.5 text-gray-400">
                                💬 subs
                              </span>
                            )}
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
