"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Brush,
  Check,
  ChevronDown,
  Download,
  Frame,
  Image as ImageIcon,
  Loader2,
  Palette,
  RectangleHorizontal,
  Save,
  Sparkles,
  Star,
  Trash2,
  Wand2,
} from "lucide-react";
import AppShell from "@/components/AppShell";
import { apiFetch } from "@/lib/api";
import { copyText } from "@/lib/clipboard";

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
interface Template {
  id: string; emoji: string; label: string; kind: string; style: string; palette: string; idea: string;
}
interface Brand {
  brand_name: string; tagline: string;
  color_primary: string; color_secondary: string; color_accent: string;
  font_vibe: string; logo_design_id: string; has_logo: boolean;
}
const EMPTY_BRAND: Brand = {
  brand_name: "", tagline: "", color_primary: "", color_secondary: "", color_accent: "",
  font_vibe: "modern", logo_design_id: "", has_logo: false,
};

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
const FONT_VIBES = ["classic", "modern", "bold"];

/* ---------------------------------------------------------------- page */
export default function DesignPage() {
  const [presets, setPresets] = useState<Presets | null>(null);
  const [exports, setExports] = useState<{ id: string; label: string }[]>([]);
  const [orders, setOrders] = useState<{ id: string; token: string; path: string; status: string; customer_name: string | null; kind: string; idea: string | null }[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [designs, setDesigns] = useState<Design[]>([]);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [kind, setKind] = useState<"flyer" | "logo" | "banner">("flyer");
  const [idea, setIdea] = useState("");
  const [style, setStyle] = useState("minimal");
  const [palette, setPalette] = useState("auto");
  const [transparent, setTransparent] = useState(false);
  const [enhance, setEnhance] = useState(true);
  const [brand, setBrand] = useState<Brand>(EMPTY_BRAND);
  const [brandOpen, setBrandOpen] = useState(false);
  const [useBrand, setUseBrand] = useState(false);
  const [savingBrand, setSavingBrand] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  // 🔁 batch studio
  const [bHead, setBHead] = useState("");
  const [bSub, setBSub] = useState("");
  const [bCta, setBCta] = useState("");
  const [bAccent, setBAccent] = useState("#FFD54A");
  const [bFiles, setBFiles] = useState<File[]>([]);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvTheme, setCsvTheme] = useState("noir");
  const [bBusy, setBBusy] = useState(false);
  const urlCache = useRef<Record<string, string>>({});

  const flash = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 4500); };

  const thumbFor = useCallback(async (id: string) => {
    if (urlCache.current[id]) return;
    try {
      const blob = await apiFetch<Blob>(`/media/designs/${id}/download?tier=web`);
      const u = URL.createObjectURL(blob);
      urlCache.current[id] = u;
      setThumbs((t) => ({ ...t, [id]: u }));
    } catch { /* file may be gone */ }
  }, []);

  const refresh = useCallback(async () => {
    const j = await apiFetch<{ designs: Design[] }>("/media/designs");
    setDesigns(j.designs);
    j.designs.forEach((d) => thumbFor(d.id));
  }, [thumbFor]);

  useEffect(() => {
    apiFetch<Presets>("/media/designs/presets").then(setPresets).catch(() => flash("Could not load presets"));
    apiFetch<{ templates: Template[] }>("/media/designs/templates").then((j) => setTemplates(j.templates)).catch(() => {});
    apiFetch<{ presets: { id: string; label: string }[] }>("/media/designs/exports").then((j) => setExports(j.presets)).catch(() => {});
    apiFetch<{ orders: typeof orders }>("/media/design-orders").then((j) => setOrders(j.orders)).catch(() => {});
    apiFetch<Brand>("/media/brand").then((b) => {
      setBrand(b);
      if (b.brand_name) setBrandOpen(false);
    }).catch(() => {});
    refresh().catch(() => {});
    const cache = urlCache.current;
    return () => Object.values(cache).forEach((u) => URL.revokeObjectURL(u));
  }, [refresh]);

  function loadTemplate(t: Template) {
    setKind(t.kind as typeof kind);
    setStyle(t.style);
    setPalette(t.palette);
    setIdea(t.idea);
    flash(`${t.emoji} ${t.label} loaded — edit the [brackets], then Generate.`);
    window.scrollTo({ top: 200, behavior: "smooth" });
  }

  async function saveBrand() {
    setSavingBrand(true);
    try {
      const b = await apiFetch<Brand>("/media/brand", { method: "PUT", body: JSON.stringify(brand) });
      setBrand(b);
      flash("⭐ Brand Kit saved — toggle 'Use my brand' on any design.");
    } catch (e) {
      flash(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSavingBrand(false);
    }
  }

  async function generate() {
    if (idea.trim().length < 3 || busy) return;
    setBusy(true);
    try {
      const d = await apiFetch<Design>("/media/designs", {
        method: "POST",
        body: JSON.stringify({
          idea: idea.trim(), kind, style, palette,
          transparent: kind === "logo" && transparent, enhance,
          use_brand: useBrand,
        }),
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

  // ---------------------------------------------------- 🔁 batch studio
  async function runBatchPhotos() {
    if (bBusy || !bFiles.length || bHead.trim().length < 2) return;
    setBBusy(true);
    try {
      const fd = new FormData();
      bFiles.slice(0, 10).forEach((f) => fd.append("files", f, f.name));
      fd.append("headline", bHead.trim());
      if (bSub.trim()) fd.append("sub", bSub.trim());
      if (bCta.trim()) fd.append("cta", bCta.trim());
      fd.append("accent", bAccent);
      const j = await apiFetch<{ designs: Design[]; skipped: string[]; trimmed: number; remaining_today: number }>(
        "/media/designs/batch", { method: "POST", body: fd });
      flash(`🔁 ${j.designs.length} flyers rendered${j.skipped.length ? ` · skipped ${j.skipped.join(", ")}` : ""}${j.trimmed ? ` · ${j.trimmed} over today's limit` : ""} — in your gallery below`);
      setBFiles([]); setBHead(""); setBSub(""); setBCta("");
      refresh();
    } catch (e) {
      flash(e instanceof Error ? e.message : "Batch failed");
    } finally {
      setBBusy(false);
    }
  }

  async function runBatchCsv() {
    if (bBusy || !csvFile) return;
    setBBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", csvFile, csvFile.name);
      fd.append("accent", bAccent);
      fd.append("theme", csvTheme);
      const j = await apiFetch<{ designs: Design[]; rows: number; remaining_today: number }>(
        "/media/designs/batch-csv", { method: "POST", body: fd });
      flash(`🔁 ${j.rows} card flyers rendered from ${csvFile.name} — check your gallery`);
      setCsvFile(null);
      refresh();
    } catch (e) {
      flash(e instanceof Error ? e.message : "CSV batch failed");
    } finally {
      setBBusy(false);
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

  async function exportPreset(id: string, preset: string, d: Design) {
    if (!preset) return;
    try {
      const blob = await apiFetch<Blob>(`/media/designs/${id}/export?preset=${preset}`);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `mood-${d.kind}-${id.slice(0, 8)}-${preset}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch (e) {
      flash(e instanceof Error ? e.message : "Export failed");
    }
  }

  async function createOrderLink() {
    try {
      const j = await apiFetch<{ token: string; path: string }>("/media/design-orders", {
        method: "POST", body: JSON.stringify({}),
      });
      const url = `${window.location.origin}${j.path}`;
      (await copyText(url))
        ? flash(`🔗 Client order link copied — ${url}`)
        : flash(`🔗 Client order link (long-press to copy): ${url}`);
      const list = await apiFetch<{ orders: typeof orders }>("/media/design-orders");
      setOrders(list.orders);
    } catch (e) {
      flash(e instanceof Error ? e.message : "Link failed");
    }
  }

  async function copyOrder(path: string) {
    const url = `${window.location.origin}${path}`;
    (await copyText(url))
      ? flash("🔗 Order link copied to clipboard")
      : flash(`🔗 Order link (long-press to copy): ${url}`);
  }

  async function closeOrder(id: string) {
    try {
      await apiFetch(`/media/design-orders/${id}/close`, { method: "POST" });
      setOrders((os) => os.map((o) => (o.id === id ? { ...o, status: "closed" } : o)));
    } catch (e) {
      flash(e instanceof Error ? e.message : "Close failed");
    }
  }

  async function brandIcon(size: 192 | 512) {
    try {
      const blob = await apiFetch<Blob>(`/media/brand/icon?size=${size}`);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `mood-icon-${size}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch (e) {
      flash(e instanceof Error ? e.message : "Icon failed — save a Brand Kit first");
    }
  }

  async function remove(id: string) {
    try {
      await apiFetch(`/media/designs/${id}`, { method: "DELETE" });
      setDesigns((ds) => ds.filter((d) => d.id !== id));
      if (urlCache.current[id]) URL.revokeObjectURL(urlCache.current[id]);
      delete urlCache.current[id];
      setThumbs((t) => { const n = { ...t }; delete n[id]; return n; });
      if (brand.logo_design_id === id) setBrand((b) => ({ ...b, logo_design_id: "" }));
    } catch (e) {
      flash(e instanceof Error ? e.message : "Delete failed");
    }
  }

  const kp = presets?.kinds.find((k) => k.id === kind);
  const logos = designs.filter((d) => d.kind === "logo");

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

        {/* ✈️ templates */}
        {templates.length > 0 && (
          <section>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">✈️ Quick templates</h2>
            <div className="flex gap-2 overflow-x-auto pb-1 -mx-1 px-1">
              {templates.map((t) => (
                <button
                  key={t.id}
                  onClick={() => loadTemplate(t)}
                  className="touch-manipulation shrink-0 rounded-xl border border-line bg-white/5 px-3 py-2 text-left hover:border-accent/50 transition"
                  title={`${t.kind} · ${t.style} · ${t.palette}`}
                >
                  <span className="text-base">{t.emoji}</span>
                  <div className="text-[11px] font-medium text-gray-200 mt-0.5 whitespace-nowrap">{t.label}</div>
                </button>
              ))}
            </div>
          </section>
        )}

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
                <div className="text-[10px] text-gray-500">{p ? `${p.print[0]}×${p.print[1]} print` : ""}</div>
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
                ? "e.g. Grand Opening Flyer — 'DUMSOR BURGER' opens Aug 1, Oxford St, Osu. Buy 1 get 1 free. Bold street-food energy"
                : "e.g. Website banner for a fintech savings app — 'Grow your money' headline, calm trust-blue"
          }
          className="w-full rounded-xl border border-line bg-white/5 p-3 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-accent resize-none"
        />
        <p className="text-[11px] text-gray-500 -mt-4">💡 Put exact text in 'quotes' — the art director keeps spelling intact.</p>

        {/* styles */}
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Style</h2>
          <div className="flex flex-wrap gap-2">
            {(presets?.styles ?? []).map((s) => (
              <button key={s.id} onClick={() => setStyle(s.id)} title={s.hint}
                className={`touch-manipulation rounded-full border px-3 py-1.5 text-xs transition ${
                  style === s.id ? "border-accent bg-accent/15 text-accent" : "border-line text-gray-300 hover:border-accent/40"
                }`}>{s.id}</button>
            ))}
          </div>
        </section>

        {/* palettes */}
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Palette</h2>
          <div className="flex flex-wrap gap-2">
            {(presets?.palettes ?? []).map((p) => (
              <button key={p.id} onClick={() => setPalette(p.id)} title={p.hint || "AI picks"}
                className={`touch-manipulation flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs transition ${
                  palette === p.id ? "border-accent bg-accent/15 text-accent" : "border-line text-gray-300 hover:border-accent/40"
                }`}>
                <span className="h-3.5 w-3.5 rounded-full border border-white/20" style={{ background: PALETTE_SWATCH[p.id] }} />
                {p.id}
              </button>
            ))}
          </div>
        </section>

        {/* ⭐ brand kit */}
        <section className="rounded-xl border border-line bg-white/5 overflow-hidden">
          <button onClick={() => setBrandOpen((o) => !o)}
            className="touch-manipulation w-full flex items-center gap-2 px-4 py-3 text-left">
            <Star size={15} className={brand.brand_name ? "text-amber-400" : "text-gray-500"} />
            <span className="text-sm font-semibold text-gray-100">My Brand Kit</span>
            {brand.brand_name && <span className="text-xs text-gray-500">· {brand.brand_name}</span>}
            <ChevronDown size={15} className={`ml-auto text-gray-500 transition-transform ${brandOpen ? "rotate-180" : ""}`} />
          </button>
          {brandOpen && (
            <div className="px-4 pb-4 space-y-3 border-t border-line pt-3">
              <div className="grid sm:grid-cols-2 gap-2">
                <input value={brand.brand_name} maxLength={120}
                  onChange={(e) => setBrand((b) => ({ ...b, brand_name: e.target.value }))}
                  placeholder="Brand name — e.g. Akwaaba Coffee"
                  className="rounded-lg border border-line bg-white/5 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-accent" />
                <input value={brand.tagline} maxLength={200}
                  onChange={(e) => setBrand((b) => ({ ...b, tagline: e.target.value }))}
                  placeholder="Tagline (optional) — e.g. Sip happiness"
                  className="rounded-lg border border-line bg-white/5 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-accent" />
              </div>
              <div className="flex flex-wrap items-center gap-4">
                {(["color_primary", "color_secondary", "color_accent"] as const).map((k, i) => (
                  <label key={k} className="flex items-center gap-2 text-xs text-gray-400">
                    <input type="color" value={brand[k] || ["#7c9bff", "#0b0f14", "#d4af37"][i]}
                      onChange={(e) => setBrand((b) => ({ ...b, [k]: e.target.value }))}
                      className="h-8 w-10 cursor-pointer rounded border border-line bg-transparent" />
                    {["Primary", "Secondary", "Accent"][i]}
                  </label>
                ))}
                <div className="flex items-center gap-1.5">
                  {FONT_VIBES.map((f) => (
                    <button key={f} onClick={() => setBrand((b) => ({ ...b, font_vibe: f }))}
                      className={`touch-manipulation rounded-full border px-2.5 py-1 text-[11px] transition ${
                        brand.font_vibe === f ? "border-accent bg-accent/15 text-accent" : "border-line text-gray-400"
                      }`}>{f}</button>
                  ))}
                </div>
              </div>
              {/* logo picker */}
              <div>
                <p className="text-xs text-gray-400 mb-1.5">
                  Brand logo <span className="text-gray-600">(from your logo designs — gets composited onto flyers & banners)</span>:
                </p>
                {logos.length === 0 ? (
                  <p className="text-[11px] text-gray-600">No logo designs yet — switch to 🖌 Logo mode above and generate one first.</p>
                ) : (
                  <div className="flex gap-2 overflow-x-auto pb-1">
                    {logos.map((d) => (
                      <button key={d.id}
                        onClick={() => setBrand((b) => ({ ...b, logo_design_id: b.logo_design_id === d.id ? "" : d.id }))}
                        className={`touch-manipulation relative h-16 w-16 shrink-0 rounded-lg border overflow-hidden bg-[repeating-conic-gradient(#1b2230_0%_25%,#151b26_0%_50%)] bg-[length:10px_10px] transition ${
                          brand.logo_design_id === d.id ? "border-accent ring-2 ring-accent/40" : "border-line hover:border-accent/40"
                        }`}>
                        {thumbs[d.id]
                          // eslint-disable-next-line @next/next/no-img-element
                          ? <img src={thumbs[d.id]} alt="logo option" className="h-full w-full object-contain" />
                          : <Loader2 size={14} className="m-auto animate-spin text-gray-600" />}
                        {brand.logo_design_id === d.id && (
                          <span className="absolute right-0.5 top-0.5 rounded-full bg-accent p-0.5 text-[#0b0f14]"><Check size={9} /></span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button onClick={saveBrand} disabled={savingBrand}
                className="touch-manipulation flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-[#0b0f14] disabled:opacity-40">
                {savingBrand ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Save Brand Kit
              </button>
              {brand.brand_name && brand.color_primary && (
                <span className="flex items-center gap-2 text-[11px] text-gray-500">
                  App icon:
                  <button onClick={() => brandIcon(192)} className="touch-manipulation rounded-lg border border-line px-2 py-1 text-[10px] text-gray-300 hover:border-accent/50">192px</button>
                  <button onClick={() => brandIcon(512)} className="touch-manipulation rounded-lg border border-line px-2 py-1 text-[10px] text-gray-300 hover:border-accent/50">512px</button>
                  <span className="text-gray-600">(color tile + initial — PWA-ready)</span>
                </span>
              )}
            </div>
          )}
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
          {brand.brand_name && kind !== "logo" && (
            <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer select-none">
              <input type="checkbox" checked={useBrand} onChange={(e) => setUseBrand(e.target.checked)} className="accent-[rgb(var(--mood-accent))]" />
              <Star size={12} className="text-amber-400" /> Use my brand{brand.has_logo ? " (logo included)" : ""}
            </label>
          )}
          <button onClick={generate} disabled={busy || idea.trim().length < 3}
            className="touch-manipulation ml-auto flex items-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-[#0b0f14] disabled:opacity-40 hover:brightness-110 transition">
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

        {/* 🔁 batch studio */}
        <section className="rounded-xl border border-line bg-white/5 p-4 space-y-3">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-sm font-semibold text-gray-100">🔁 Batch studio</h2>
            <span className="text-[11px] text-gray-500">one headline → up to 10 matching flyers · renders locally (no AI tokens), respects your daily design budget</span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <input value={bHead} onChange={(e) => setBHead(e.target.value)} maxLength={90}
              placeholder="Headline — e.g. Grand Sale 50% Off"
              className="rounded-xl border border-line bg-transparent px-3 py-2 text-sm outline-none focus:border-accent/60" />
            <div className="flex gap-2">
              <input value={bSub} onChange={(e) => setBSub(e.target.value)} maxLength={120}
                placeholder="Sub-line (optional)"
                className="min-w-0 flex-1 rounded-xl border border-line bg-transparent px-3 py-2 text-sm outline-none focus:border-accent/60" />
              <input value={bCta} onChange={(e) => setBCta(e.target.value)} maxLength={40}
                placeholder="CTA"
                className="w-24 rounded-xl border border-line bg-transparent px-3 py-2 text-sm outline-none focus:border-accent/60" />
              <label className="relative h-9 w-9 shrink-0 self-center overflow-hidden rounded-lg border border-line cursor-pointer" title="Accent color">
                <span className="absolute inset-0" style={{ background: bAccent }} />
                <input type="color" value={bAccent} onChange={(e) => setBAccent(e.target.value)} className="absolute inset-0 opacity-0 cursor-pointer" />
              </label>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <label className="touch-manipulation cursor-pointer rounded-xl border border-dashed border-line px-4 py-2 text-xs text-gray-300 hover:border-accent/50 transition">
              📷 {bFiles.length ? `${bFiles.length} photo${bFiles.length > 1 ? "s" : ""} picked` : "Pick up to 10 photos"}
              <input type="file" accept="image/png,image/jpeg,image/webp" multiple className="hidden"
                onChange={(e) => setBFiles(Array.from(e.target.files ?? []).slice(0, 10))} />
            </label>
            <button onClick={runBatchPhotos} disabled={bBusy || !bFiles.length || bHead.trim().length < 2}
              className="touch-manipulation rounded-xl bg-accent px-4 py-2 text-xs font-semibold text-[#0b0f14] disabled:opacity-40 hover:brightness-110 transition">
              {bBusy ? <Loader2 size={14} className="animate-spin inline" /> : "🔁"} Render flyer set
            </button>
            <span className="text-gray-600 text-xs">·</span>
            <label className="touch-manipulation cursor-pointer rounded-xl border border-dashed border-line px-4 py-2 text-xs text-gray-300 hover:border-accent/50 transition">
              🧾 {csvFile ? csvFile.name : "CSV → flyers"}
              <input type="file" accept=".csv,text/csv" className="hidden"
                onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)} />
            </label>
            <select value={csvTheme} onChange={(e) => setCsvTheme(e.target.value)}
              className="rounded-lg border border-line bg-[rgb(var(--mood-panel))] px-2 py-1.5 text-[11px] text-gray-300">
              {["noir", "sunset", "ocean", "forest", "candy", "gold"].map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <button onClick={runBatchCsv} disabled={bBusy || !csvFile}
              className="touch-manipulation rounded-xl border border-line px-4 py-2 text-xs text-gray-200 disabled:opacity-40 hover:border-accent/50 transition">
              Render CSV
            </button>
          </div>
          <p className="text-[10px] text-gray-600">CSV headers: <code>headline,sub,cta,accent</code> (headline required; one card flyer per row).</p>
        </section>

        {/* 🛍 client mode */}
        <section className="rounded-xl border border-line bg-white/5 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-gray-100">🛍 Client mode</h2>
            <span className="text-[11px] text-gray-500">share a magic link — clients order, you approve in the ✋ inbox, they download from the same link</span>
          </div>
          <button onClick={createOrderLink}
            className="touch-manipulation rounded-xl bg-accent px-4 py-2 text-xs font-semibold text-[#0b0f14] hover:brightness-110 transition">
            🔗 New order link (copies to clipboard)
          </button>
          {orders.length > 0 && (
            <div className="space-y-1.5 pt-1">
              {orders.slice(0, 6).map((o) => (
                <div key={o.id} className="flex items-center gap-2 rounded-lg border border-line px-3 py-2">
                  <span className={`text-[10px] rounded-full px-2 py-0.5 border ${
                    o.status === "delivered" ? "border-emerald-400/50 text-emerald-400"
                    : o.status === "staged" ? "border-amber-400/50 text-amber-300"
                    : o.status === "closed" ? "border-line text-gray-600" : "border-accent/40 text-accent"}`}>
                    {o.status === "staged" ? "✋ waiting your approval" : o.status}
                  </span>
                  <span className="text-[11px] text-gray-400 truncate flex-1">
                    {o.customer_name ? `${o.customer_name} — ` : ""}{o.kind}{o.idea ? ` · ${o.idea}` : ""}
                  </span>
                  {o.status !== "closed" && (
                    <>
                      <button onClick={() => copyOrder(o.path)} className="touch-manipulation rounded-lg border border-line px-2 py-1 text-[10px] text-gray-300 hover:border-accent/50">🔗</button>
                      <button onClick={() => closeOrder(o.id)} className="touch-manipulation rounded-lg border border-line px-2 py-1 text-[10px] text-gray-500 hover:text-red-400">✕</button>
                    </>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* gallery */}
        <section>
          <h2 className="text-sm font-semibold text-gray-100 mb-3">My designs <span className="text-gray-500 font-normal">({designs.length})</span></h2>
          {designs.length === 0 ? (
            <div className="rounded-xl border border-dashed border-line p-10 text-center text-sm text-gray-500">
              <ImageIcon className="mx-auto mb-2 text-gray-600" />
              No designs yet — tap a template above or describe your flyer/logo.
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
                    {brand.logo_design_id === d.id && (
                      <span className="absolute right-2 top-2 rounded-full bg-amber-400/90 px-1.5 py-0.5 text-[9px] font-bold text-black">BRAND LOGO</span>
                    )}
                  </div>
                  <div className="p-2.5 space-y-2">
                    <p className="line-clamp-2 text-[11px] text-gray-400 min-h-[2rem]">{d.idea}</p>
                    <div className="flex items-center gap-1.5">
                      <button onClick={() => download(d.id, "web", d)} title={`${d.width}×${d.height} — socials & web`}
                        className="touch-manipulation flex-1 rounded-lg border border-line px-2 py-1.5 text-[10px] text-gray-300 hover:border-accent/50 transition">
                        <Download size={11} className="inline mr-1 -mt-0.5" />Web
                      </button>
                      <button onClick={() => download(d.id, "print", d)} title="300 DPI upscaled — print & merch"
                        className="touch-manipulation flex-1 rounded-lg bg-accent/15 border border-accent/40 px-2 py-1.5 text-[10px] font-semibold text-accent hover:bg-accent/25 transition">
                        <Download size={11} className="inline mr-1 -mt-0.5" />Print HD
                      </button>
                      <select
                        value=""
                        onChange={(e) => { exportPreset(d.id, e.target.value, d); e.target.value = ""; }}
                        title="🖨 Print-shop & social exports"
                        className="touch-manipulation rounded-lg border border-line bg-panel px-1.5 py-1.5 text-[10px] text-gray-300 outline-none hover:border-accent/50"
                      >
                        <option value="" disabled>🖨…</option>
                        {exports.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
                      </select>
                      <button onClick={() => remove(d.id)} title="Delete design"
                        className="touch-manipulation rounded-lg border border-line px-2 py-1.5 text-gray-500 hover:text-red-400 hover:border-red-400/40 transition">
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
