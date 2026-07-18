"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Brush,
  RectangleHorizontal,
  Download,
  Frame,
  Image as ImageIcon,
  Loader2,
  Palette,
  Sparkles,
  Trash2,
  Wand2,
} from "lucide-react";
import AppShell from "@/components/AppShell";
import { apiFetch } from "@/lib/api";

/* ---------------------------------------------------------------- types */
interface Design {
  id: string;
  kind: "flyer" | "logo" | "banner";
  idea: string;
  brief: string;
  style: string;
  palette: string;
  transparent: boolean;
  width: number;
  height: number;
  note: string | null;
  created_at: string | null;
}
interface Presets {
  kinds: { id: string; label: string; web: number[]; print: number[]; hint: string }[];
  styles: { id: string; hint: string }[];
  palettes: { id: string; hint: string }[];
}

const KIND_ICONS = { flyer: Frame, logo: Brush, banner: RectangleHorizontal } as const;
const PALETTE_SWATCH: Record<string, string> = {
  auto: "conic-gradient(#888,#ddd,#888)",
  noir: "linear-gradient(135deg,#111 50%,#fff 50%)",
  sunset: "linear-gradient(135deg,#ff7e5f,#feb47b,#d23b8f)",
  ocean: "linear-gradient(135deg,#0f4c81,#3aa99e)",
  forest: "linear-gradient(135deg,#1d4d2b,#e8dcc0)",
  gold: "linear-gradient(135deg,#0a0a0a 40%,#d4af37)",
  candy: "linear-gradient(135deg,#ffb3d9,#b3ffd9,#d9b3ff)",
};

/* ---------------------------------------------------------------- page */
export default function DesignPage() {
  const [presets, setPresets] = useState<Presets | null>(null);
  const [designs, setDesigns] = useState<Design[]>([]);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [kind, setKind] = useState<"flyer" | "logo" | "banner">("flyer");
  const [idea, setIdea] = useState("");
  const [style, setStyle] = useState("minimal");
  const [palette, setPalette] = useState("auto");
  const [transparent, setTransparent] = useState(false);
  const [enhance, setEnhance] = useState(true);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const urlCache = useRef<Record<string, string>>({});

  const flash = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 4000);
  };

  const thumbFor = useCallback(async (id: string) => {
    if (urlCache.current[id]) return;
    try {
      const blob = await apiFetch<Blob>(`/media/designs/${id}/download?tier=web`);
      const u = URL.createObjectURL(blob);
      urlCache.current[id] = u;
      setThumbs((t) => ({ ...t, [id]: u }));
    } catch {
      /* file may be gone; leave blank */
    }
  }, []);

  const refresh = useCallback(async () => {
    const j = await apiFetch<{ designs: Design[] }>("/media/designs");
    setDesigns(j.designs);
    j.designs.forEach((d) => thumbFor(d.id));
  }, [thumbFor]);

  useEffect(() => {
    apiFetch<Presets>("/media/designs/presets").then(setPresets).catch(() => flash("Could not load presets"));
    refresh().catch(() => {});
    const cache = urlCache.current;
    return () => Object.values(cache).forEach((u) => URL.revokeObjectURL(u));
  }, [refresh]);

  async function generate() {
    if (idea.trim().length < 3 || busy) return;
    setBusy(true);
    try {
      const d = await apiFetch<Design>("/media/designs", {
        method: "POST",
        body: JSON.stringify({ idea: idea.trim(), kind, style, palette, transparent: kind === "logo" && transparent, enhance }),
      });
      setDesigns((ds) => [d, ...ds]);
      thumbFor(d.id);
      if (d.note) flash(d.note);
      else flash("✨ Design ready — grab the Print HD file for crisp output!");
    } catch (e) {
      flash(e instanceof Error ? e.message : "Design failed");
    } finally {
      setBusy(false);
    }
  }

  async function download(id: string, tier: "web" | "print", d: Design) {
    try {
      const blob = await apiFetch<Blob>(`/media/designs/${id}/download?tier=${tier}`);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `mood-${d.kind}-${id.slice(0, 8)}-${tier === "print" ? "print-hd" : "web"}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch (e) {
      flash(e instanceof Error ? e.message : "Download failed");
    }
  }

  async function remove(id: string) {
    try {
      await apiFetch(`/media/designs/${id}`, { method: "DELETE" });
      setDesigns((ds) => ds.filter((d) => d.id !== id));
      if (urlCache.current[id]) URL.revokeObjectURL(urlCache.current[id]);
      delete urlCache.current[id];
      setThumbs((t) => {
        const n = { ...t };
        delete n[id];
        return n;
      });
    } catch (e) {
      flash(e instanceof Error ? e.message : "Delete failed");
    }
  }

  const kp = presets?.kinds.find((k) => k.id === kind);

  return (
    <AppShell title="Design Studio">
      <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
        <header className="flex items-center gap-3">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-accent/15 text-accent"><Palette size={22} /></span>
          <div>
            <h1 className="text-xl font-bold text-gray-100">Design Studio</h1>
            <p className="text-xs text-gray-400">Flyers, logos & banners — AI art direction + print-grade 300 DPI output</p>
          </div>
        </header>

        {/* kind tabs */}
        <div className="grid grid-cols-3 gap-2">
          {(["flyer", "logo", "banner"] as const).map((k) => {
            const Icon = KIND_ICONS[k];
            const p = presets?.kinds.find((x) => x.id === k);
            return (
              <button
                key={k}
                onClick={() => setKind(k)}
                className={`touch-manipulation rounded-xl border p-3 text-left transition ${
                  kind === k ? "border-accent bg-accent/10" : "border-line bg-white/5 hover:border-accent/40"
                }`}
              >
                <Icon size={18} className={kind === k ? "text-accent" : "text-gray-400"} />
                <div className="mt-1 text-sm font-semibold text-gray-100 capitalize">{k}</div>
                <div className="text-[10px] text-gray-500">
                  {p ? `${p.print[0]}×${p.print[1]} print` : ""}
                </div>
              </button>
            );
          })}
        </div>

        {/* idea */}
        <textarea
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          rows={3}
          maxLength={1500}
          placeholder={
            kind === "logo"
              ? "e.g. Minimal bird mark for 'Akwaaba Coffee' — warm beans brown, wordmark under a geometric bird"
              : kind === "flyer"
                ? "e.g. Grand Opening Flyer — 'DUMSOR BURGER' opens Aug 1, Oxfood St, Osu. Buy 1 get 1 free. Bold street-food energy"
                : "e.g. Website banner for a fintech savings app — 'Grow your money' headline, calm trust-blue"
          }
          className="w-full rounded-xl border border-line bg-white/5 p-3 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-accent resize-none"
        />
        <p className="text-[11px] text-gray-500 -mt-4">
          💡 Put exact text in 'quotes' — the art director keeps spelling intact.
        </p>

        {/* styles */}
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Style</h2>
          <div className="flex flex-wrap gap-2">
            {(presets?.styles ?? []).map((s) => (
              <button
                key={s.id}
                onClick={() => setStyle(s.id)}
                title={s.hint}
                className={`touch-manipulation rounded-full border px-3 py-1.5 text-xs transition ${
                  style === s.id ? "border-accent bg-accent/15 text-accent" : "border-line text-gray-300 hover:border-accent/40"
                }`}
              >
                {s.id}
              </button>
            ))}
          </div>
        </section>

        {/* palettes */}
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Palette</h2>
          <div className="flex flex-wrap gap-2">
            {(presets?.palettes ?? []).map((p) => (
              <button
                key={p.id}
                onClick={() => setPalette(p.id)}
                title={p.hint || "AI picks"}
                className={`touch-manipulation flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs transition ${
                  palette === p.id ? "border-accent bg-accent/15 text-accent" : "border-line text-gray-300 hover:border-accent/40"
                }`}
              >
                <span className="h-3.5 w-3.5 rounded-full border border-white/20" style={{ background: PALETTE_SWATCH[p.id] }} />
                {p.id}
              </button>
            ))}
          </div>
        </section>

        {/* toggles + go */}
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer select-none">
            <input type="checkbox" checked={enhance} onChange={(e) => setEnhance(e.target.checked)} className="accent-[rgb(var(--mood-accent))]" />
            <Wand2 size={13} className="text-accent" /> Art-director brief
          </label>
          {kind === "logo" && (
            <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer select-none">
              <input type="checkbox" checked={transparent} onChange={(e) => setTransparent(e.target.checked)} className="accent-[rgb(var(--mood-accent))]" />
              Transparent background
            </label>
          )}
          <button
            onClick={generate}
            disabled={busy || idea.trim().length < 3}
            className="touch-manipulation ml-auto flex items-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-[#0b0f14] disabled:opacity-40 hover:brightness-110 transition"
          >
            {busy ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
            {busy ? "Designing…" : "Generate design"}
          </button>
        </div>
        {busy && (
          <p className="text-xs text-gray-500 animate-pulse">
            Art-directing your brief → rendering {kp?.web[0]}×{kp?.web[1]} → upscaling to {kp?.print[0]}×{kp?.print[1]} at 300 DPI…
          </p>
        )}
        {toast && <div className="rounded-lg border border-accent/40 bg-accent/10 px-3 py-2 text-xs text-accent">{toast}</div>}

        {/* gallery */}
        <section>
          <h2 className="text-sm font-semibold text-gray-100 mb-3">My designs <span className="text-gray-500 font-normal">({designs.length})</span></h2>
          {designs.length === 0 ? (
            <div className="rounded-xl border border-dashed border-line p-10 text-center text-sm text-gray-500">
              <ImageIcon className="mx-auto mb-2 text-gray-600" />
              No designs yet — describe your flyer or logo above and hit Generate.
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {designs.map((d) => (
                <div key={d.id} className="group rounded-xl border border-line bg-white/5 overflow-hidden">
                  <div className="relative aspect-square bg-[repeating-conic-gradient(#1b2230_0%_25%,#151b26_0%_50%)] bg-[length:16px_16px] grid place-items-center overflow-hidden">
                    {thumbs[d.id] ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={thumbs[d.id]} alt={d.idea} className="max-h-full max-w-full object-contain" />
                    ) : (
                      <Loader2 className="animate-spin text-gray-600" />
                    )}
                    <span className="absolute left-2 top-2 rounded-full bg-black/60 px-2 py-0.5 text-[10px] capitalize text-gray-200 backdrop-blur">{d.kind}</span>
                  </div>
                  <div className="p-2.5 space-y-2">
                    <p className="line-clamp-2 text-[11px] text-gray-400 min-h-[2rem]">{d.idea}</p>
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => download(d.id, "web", d)}
                        className="touch-manipulation flex-1 rounded-lg border border-line px-2 py-1.5 text-[10px] text-gray-300 hover:border-accent/50 transition"
                        title={`${d.width}×${d.height} — socials & web`}
                      >
                        <Download size={11} className="inline mr-1 -mt-0.5" />
                        Web
                      </button>
                      <button
                        onClick={() => download(d.id, "print", d)}
                        className="touch-manipulation flex-1 rounded-lg bg-accent/15 border border-accent/40 px-2 py-1.5 text-[10px] font-semibold text-accent hover:bg-accent/25 transition"
                        title="300 DPI upscaled — print & merch"
                      >
                        <Download size={11} className="inline mr-1 -mt-0.5" />
                        Print HD
                      </button>
                      <button
                        onClick={() => remove(d.id)}
                        className="touch-manipulation rounded-lg border border-line px-2 py-1.5 text-gray-500 hover:text-red-400 hover:border-red-400/40 transition"
                        title="Delete design"
                      >
                        <Trash2 size={11} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </AppShell>
  );
}
