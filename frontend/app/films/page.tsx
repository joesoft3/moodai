"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Clapperboard, Clapperboard as FilmIcon, Copy, Loader2, PencilLine, RefreshCw, RotateCcw, Trash2 } from "lucide-react";
import AppShell from "@/components/AppShell";
import { apiFetch } from "@/lib/api";

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
  subtitles: boolean;
  url: string;
  script: string | null;
  note: string | null;
  scenes: { shot: string; narration: string }[];
  created_at: string | null;
}

function chip(text: string, accent = false) {
  return (
    <span
      key={text}
      className={`text-[10px] rounded-full border px-2 py-0.5 ${
        accent ? "bg-accent/10 border-accent/30 text-accent" : "bg-white/5 border-line text-gray-500"
      }`}
    >
      {text}
    </span>
  );
}

function RenderingCard({ film }: { film: Film }) {
  const pct = film.scene_count ? Math.round((film.progress / film.scene_count) * 100) : 0;
  return (
    <div className="aspect-video rounded-xl border border-line bg-panel flex flex-col items-center justify-center gap-2 px-4">
      <Loader2 size={22} className="animate-spin text-accent" />
      <p className="text-[11px] text-gray-400 text-center">
        🎬 Filming your storyboard… scene {Math.min(film.progress + 1, film.scene_count)}/{film.scene_count}
      </p>
      <div className="w-3/4 h-1.5 rounded-full bg-white/5 overflow-hidden">
        <div className="h-full rounded-full bg-accent/70 transition-all" style={{ width: `${Math.max(4, pct)}%` }} />
      </div>
      <p className="text-[10px] text-gray-600">renders run 2-wide · stitching + mixing come next</p>
    </div>
  );
}

export default function FilmsPage() {
  const [films, setFilms] = useState<Film[] | null>(null);
  const [jobsRunning, setJobsRunning] = useState(0);
  const [msg, setMsg] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch<{ films: Film[]; jobs_running: number }>("/media/films");
      setFilms(res.films);
      setJobsRunning(res.jobs_running);
    } catch {
      /* keep last good state */
    }
  }, []);

  useEffect(() => {
    let stopped = false;
    async function loop() {
      await load();
      if (!stopped) timer.current = setTimeout(loop, 8000);
    }
    loop();
    return () => {
      stopped = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [load]);

  async function remove(id: string, prompt: string) {
    if (!confirm(`Delete this film?\n\n"${prompt.slice(0, 80)}"`)) return;
    try {
      await apiFetch(`/media/films/${id}`, { method: "DELETE" });
      setFilms((f) => (f ?? []).filter((x) => x.id !== id));
    } catch (e: any) {
      setMsg("⚠️ " + (e.message ?? "Delete failed"));
    }
  }

  async function resume(id: string) {
    setMsg("");
    try {
      await apiFetch(`/media/films/${id}/resume`, { method: "POST" });
      setMsg("↻ Render relaunched — polling continues below.");
      await load();
    } catch (e: any) {
      setMsg("⚠️ " + (e.message ?? "Resume failed"));
    }
  }

  async function copyLink(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setMsg("🔗 Film link copied (public, works for ~24h).");
      setTimeout(() => setMsg(""), 3000);
    } catch {
      setMsg("⚠️ Clipboard blocked — long-press the video to share instead.");
    }
  }

  const rendering = (films ?? []).filter((f) => f.status === "rendering");

  return (
    <AppShell title="Films">
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin px-4 py-6">
        <div className="max-w-5xl 2xl:max-w-7xl mx-auto space-y-5">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-lg font-semibold flex items-center gap-2">
              <FilmIcon size={18} className="text-accent" /> Your films
            </h1>
            {rendering.length > 0 && (
              <span className="text-[11px] rounded-full border border-accent/30 bg-accent/10 text-accent px-2.5 py-0.5">
                ⏺ {rendering.length} rendering
              </span>
            )}
            <button
              onClick={load}
              className="ml-auto rounded-xl bg-white/5 border border-line p-2 text-gray-300 hover:bg-white/10 transition"
              title="Refresh"
            >
              <RefreshCw size={14} />
            </button>
          </div>
          {msg && <p className="text-xs text-yellow-500">{msg}</p>}

          {!films ? (
            <p className="text-sm text-gray-600">Loading…</p>
          ) : films.length === 0 ? (
            <div className="text-center text-gray-600 pt-20 space-y-2">
              <div className="text-4xl">🎬</div>
              <p className="text-sm">No films yet — open the 🎬 Video Studio, pick "2-scene film" or more, and direct your first movie.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {films.map((f) => (
                <div key={f.id} className="rounded-xl overflow-hidden border border-line bg-panel">
                  {f.status === "rendering" ? (
                    <RenderingCard film={f} />
                  ) : f.status === "failed" ? (
                    <div className="aspect-video flex flex-col items-center justify-center gap-2 px-4 text-center">
                      <span className="text-2xl">🥀</span>
                      <p className="text-[11px] text-red-400">{f.note ?? "Render failed"}</p>
                    </div>
                  ) : (
                    // eslint-disable-next-line jsx-a11y/media-has-caption
                    <video
                      src={f.url}
                      controls
                      playsInline
                      className={`w-full bg-black ${f.aspect_ratio === "9:16" ? "aspect-[9/16] max-h-[480px] mx-auto" : f.aspect_ratio === "1:1" ? "aspect-square" : "aspect-video"}`}
                    />
                  )}
                  <div className="p-2 space-y-1.5">
                    <p className="text-[11px] text-gray-400 line-clamp-2">{f.prompt}</p>
                    <div className="flex gap-1.5 flex-wrap">
                      {chip(`🎬 ${f.scene_count}-scene`)}
                      {chip(f.aspect_ratio)}
                      {chip(f.style.replace("_", " "))}
                      {f.subtitles && chip("💬 subs")}
                      {f.audio !== "none" &&
                        chip(f.audio === "voice+ambience" ? `🎼 voice + ${f.music}` : "🎙 voiceover", true)}
                    </div>
                    {f.script && (
                      <p className="text-[10px] text-gray-500 italic line-clamp-2 border-l-2 border-accent/30 pl-2">“{f.script}”</p>
                    )}
                    {f.status !== "failed" && f.note && <p className="text-[10px] text-yellow-600 line-clamp-2">ℹ️ {f.note}</p>}
                    <div className="flex items-center gap-1.5 pt-1">
                      {f.status === "done" && f.url && (
                        <>
                          <button
                            onClick={() => copyLink(f.url)}
                            className="rounded-lg bg-white/5 border border-line px-2.5 py-1 text-[11px] text-gray-300 hover:bg-white/10 transition flex items-center gap-1"
                          >
                            <Copy size={11} /> Link
                          </button>
                          <a
                            href={`/images?story=${f.id}`}
                            className="rounded-lg bg-white/5 border border-line px-2.5 py-1 text-[11px] text-gray-300 hover:bg-white/10 transition flex items-center gap-1"
                          >
                            <PencilLine size={11} /> Edit & re-render
                          </a>
                        </>
                      )}
                      {f.status === "rendering" && jobsRunning === 0 && (
                        <button
                          onClick={() => resume(f.id)}
                          className="rounded-lg bg-accent/10 border border-accent/30 px-2.5 py-1 text-[11px] text-accent hover:bg-accent/20 transition flex items-center gap-1"
                        >
                          <RotateCcw size={11} /> Resume render
                        </button>
                      )}
                      <button
                        onClick={() => remove(f.id, f.prompt)}
                        className="rounded-lg bg-red-400/10 border border-red-400/30 px-2.5 py-1 text-[11px] text-red-400 hover:bg-red-400/20 transition flex items-center gap-1 ml-auto"
                      >
                        <Trash2 size={11} /> Delete
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
          <p className="text-[11px] text-gray-600 flex items-center gap-1.5">
            <Clapperboard size={12} /> Films render in the background — close the tab, grab a drink, come back. Muxed
            files live ~24h; download any keeper. Scene clips during render don't count again if you resume.
          </p>
        </div>
      </div>
    </AppShell>
  );
}
