import type { Metadata } from "next";
import Link from "next/link";

// 🎬 Public film share page — beautiful OG previews (video + hero poster),
// no login wall. Server-rendered from the API's public film endpoint.

const API = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(/\/+$/, "");

interface ShareFilm {
  id: string;
  title: string;
  brand_name?: string | null;
  url: string;
  poster: string;
  scenes: number;
  duration_seconds: number;
  aspect_ratio: string;
  audio: string;
  style: string;
  created_at: string | null;
}

async function loadFilm(id: string): Promise<ShareFilm | null> {
  try {
    const res = await fetch(`${API}/media/public/films/${id}`, { next: { revalidate: 300 } });
    if (!res.ok) return null;
    return (await res.json()) as ShareFilm;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const film = await loadFilm(id);
  if (!film) {
    return { title: "Film not found · Mood AI", robots: { index: false } };
  }
  const description = `${film.scenes}-scene AI film directed with Mood AI — ${
    film.audio === "voice+ambience" ? "AI voiceover + cinematic ambience" : film.audio === "voice" ? "AI voiceover" : "direction"
  }.`;
  return {
    title: `${film.title} — a Mood AI film`,
    description,
    openGraph: {
      type: "video.other",
      title: film.title,
      description,
      videos: film.url ? [{ url: film.url, type: "video/mp4" }] : undefined,
      images: film.poster ? [{ url: film.poster, alt: film.title }] : undefined,
    },
    twitter: { card: "summary_large_image", title: film.title, description, images: film.poster ? [film.poster] : undefined },
  };
}

export default async function FilmSharePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const film = await loadFilm(id);

  return (
    <main className="min-h-screen flex flex-col items-center px-4 sm:px-6 py-10 sm:py-14">
      <div className="w-full max-w-3xl space-y-6">
        <div className="text-center space-y-1">
          <Link href="/" className="text-xs uppercase tracking-[0.3em] text-accent hover:brightness-125 transition">
            Mood AI · Films
          </Link>
        </div>

        {!film ? (
          <div className="rounded-2xl border border-line bg-panel p-10 text-center space-y-3">
            <div className="text-4xl">🥀</div>
            <h1 className="font-semibold">This film link has expired</h1>
            <p className="text-sm text-gray-500">
              Films stream from a rotating 24-hour media cache. Ask the director for a fresh link — or make your own.
            </p>
          </div>
        ) : (
          <>
            <h1 className="text-center text-[clamp(1.3rem,4.5vw,2rem)] font-bold leading-tight">{film.title}</h1>

            <div className="rounded-3xl overflow-hidden border border-line bg-panel shadow-2xl shadow-black/40">
              {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
              <video
                src={film.url}
                poster={film.poster || undefined}
                preload="metadata"
                controls
                playsInline
                autoPlay={false}
                className={`w-full bg-black ${film.aspect_ratio === "9:16" ? "aspect-[9/16] max-h-[70vh] mx-auto" : film.aspect_ratio === "1:1" ? "aspect-square" : "aspect-video"}`}
              />
              <div className="flex flex-wrap items-center gap-1.5 px-4 py-3">
                <span className="text-[11px] rounded-full bg-white/5 border border-line px-2 py-0.5 text-gray-400">🎬 {film.scenes}-scene film</span>
                <span className="text-[11px] rounded-full bg-white/5 border border-line px-2 py-0.5 text-gray-400">{film.duration_seconds}s</span>
                <span className="text-[11px] rounded-full bg-white/5 border border-line px-2 py-0.5 text-gray-400">{film.aspect_ratio}</span>
                <span className="text-[11px] rounded-full bg-white/5 border border-line px-2 py-0.5 text-gray-400">{film.style.replace("_", " ")}</span>
                {film.audio !== "none" && (
                  <span className="text-[11px] rounded-full bg-accent/10 border border-accent/30 px-2 py-0.5 text-accent">
                    {film.audio === "voice+ambience" ? "🎼 AI voice + ambience" : "🎙 AI voiceover"}
                  </span>
                )}
              </div>
            </div>

            {/* Professional CTA band */}
            <div className="rounded-2xl border border-line bg-panel p-5 sm:p-6 flex flex-col sm:flex-row items-center gap-4">
              <p className="text-sm text-gray-400 text-center sm:text-left flex-1">
                {film.brand_name ? (
                  <span className="text-amber-300 font-semibold">by {film.brand_name} · </span>
                ) : null}
                <span className="text-gray-200 font-semibold">Directed with Mood AI</span> — one prompt, four model
                brains, a film with studio voice and sound. Make yours free in 30 seconds.
              </p>
              <Link
                href="/login"
                className="rounded-xl bg-accent text-black font-semibold px-5 py-3 text-sm hover:brightness-110 transition shrink-0"
              >
                🎬 Direct your own film
              </Link>
            </div>
          </>
        )}

        <footer className="flex justify-center gap-5 text-[11px] text-gray-600 pt-2">
          <Link href="/terms" className="hover:text-gray-400 transition">Terms</Link>
          <Link href="/privacy" className="hover:text-gray-400 transition">Privacy</Link>
          <span>© 2026 Mood AI · Accra</span>
        </footer>
      </div>
    </main>
  );
}
