"use client";

import { useCallback, useEffect, useState } from "react";
import { Brush, CheckCircle2, Clock, Download, Frame, Loader2, RectangleHorizontal, Send, Sparkles } from "lucide-react";
import { API } from "@/lib/api";

interface OrderInfo {
  token: string;
  status: "open" | "staged" | "delivered" | string;
  brand_name: string;
  customer_name: string | null;
  kind: string;
  style: string;
  idea: string | null;
  note: string | null;
  ready: boolean;
}

const KINDS = [
  { id: "flyer", label: "Flyer", icon: Frame },
  { id: "logo", label: "Logo", icon: Brush },
  { id: "banner", label: "Banner", icon: RectangleHorizontal },
];
const STYLES = ["minimal", "bold", "luxury", "playful", "corporate", "retro", "neon"];

export default function OrderClient({ token }: { token: string }) {
  const [info, setInfo] = useState<OrderInfo | null>(null);
  const [gone, setGone] = useState(false);
  const [name, setName] = useState("");
  const [idea, setIdea] = useState("");
  const [kind, setKind] = useState("flyer");
  const [style, setStyle] = useState("minimal");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API}/media/public/orders/${token}`, { cache: "no-store" });
      if (!res.ok) throw new Error();
      const j = (await res.json()) as OrderInfo;
      setInfo(j);
      if (j.kind) setKind(j.kind);
      if (j.style) setStyle(j.style);
      if (j.idea && !idea) setIdea(j.idea);
      if (j.customer_name && !name) setName(j.customer_name);
    } catch {
      setGone(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  // ⏳ staged → poll until delivered
  useEffect(() => {
    if (info?.status !== "staged") return;
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [info?.status, load]);

  async function submit() {
    setBusy(true);
    setErr("");
    try {
      const res = await fetch(`${API}/media/public/orders/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ customer_name: name.trim(), idea: idea.trim(), kind, style }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Submit failed");
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Submit failed");
    } finally {
      setBusy(false);
    }
  }

  const dl = (tier: "web" | "print") => `${API}/media/public/orders/${token}/download?tier=${tier}`;

  return (
    <main className="min-h-screen bg-base text-gray-100 flex items-start justify-center px-4 py-10">
      <div className="w-full max-w-lg space-y-5">
        <header className="text-center space-y-1">
          <p className="text-[11px] uppercase tracking-widest text-gray-500">Design order</p>
          <h1 className="text-2xl font-bold">
            {info?.brand_name ? <span className="text-accent">{info.brand_name}</span> : "Your designer"}
          </h1>
          <p className="text-xs text-gray-500">powered by Mood AI Design Studio ✨</p>
        </header>

        {gone && (
          <div className="rounded-xl border border-line bg-white/5 p-6 text-center text-sm text-gray-400">
            This order link is closed or never existed. Ask your designer for a fresh one 🔗
          </div>
        )}

        {!gone && !info && (
          <div className="flex justify-center py-16"><Loader2 className="animate-spin text-accent" /></div>
        )}

        {info && info.status === "open" && (
          <section className="rounded-xl border border-line bg-white/5 p-5 space-y-4">
            {info.note && <p className="text-xs text-gray-400 border-l-2 border-accent/50 pl-2">{info.note}</p>}
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={80}
              placeholder="Your name (optional)"
              className="w-full rounded-lg border border-line bg-base/40 px-3 py-2.5 text-sm outline-none focus:border-accent placeholder-gray-500"
            />
            <textarea
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              rows={4}
              maxLength={1500}
              placeholder="Describe what you need — e.g. 'Grand-Opening flyer for BOLA'S KITCHEN, Sat Aug 9, 4pm, Lapaz. Free sobolo for the first 20 people!'"
              className="w-full rounded-lg border border-line bg-base/40 px-3 py-2.5 text-sm outline-none focus:border-accent placeholder-gray-500 resize-none"
            />
            <div>
              <p className="text-[11px] uppercase tracking-wide text-gray-500 mb-1.5">Type</p>
              <div className="flex gap-2">
                {KINDS.map((k) => (
                  <button key={k.id} onClick={() => setKind(k.id)}
                    className={`touch-manipulation flex-1 rounded-lg border px-2 py-2 text-xs flex items-center justify-center gap-1.5 transition ${
                      kind === k.id ? "border-accent bg-accent/15 text-accent" : "border-line text-gray-300"
                    }`}>
                    <k.icon size={13} /> {k.label}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wide text-gray-500 mb-1.5">Style</p>
              <div className="flex flex-wrap gap-1.5">
                {STYLES.map((st) => (
                  <button key={st} onClick={() => setStyle(st)}
                    className={`touch-manipulation rounded-full border px-2.5 py-1 text-[11px] transition ${
                      style === st ? "border-accent bg-accent/15 text-accent" : "border-line text-gray-400"
                    }`}>{st}</button>
                ))}
              </div>
            </div>
            {err && <p className="text-xs text-red-400">{err}</p>}
            <button
              onClick={submit}
              disabled={busy || idea.trim().length < 5}
              className="touch-manipulation w-full flex items-center justify-center gap-2 rounded-xl bg-accent py-3 text-sm font-semibold text-[#0b0f14] disabled:opacity-40 hover:brightness-110 transition"
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />} Send my order
            </button>
          </section>
        )}

        {info && info.status === "staged" && (
          <section className="rounded-xl border border-line bg-white/5 p-6 text-center space-y-3">
            <Clock size={22} className="mx-auto text-amber-300" />
            <h2 className="text-base font-semibold">Order received{info.customer_name ? `, ${info.customer_name}` : ""}! 🎉</h2>
            <p className="text-xs text-gray-400">
              Your designer reviews &amp; renders it shortly — this page updates itself (checks every 20s).
              Keep the link; your downloads appear right here.
            </p>
            {info.idea && <p className="text-[11px] text-gray-500 border-l-2 border-accent/40 pl-2 text-left">“{info.idea.slice(0, 140)}”</p>}
          </section>
        )}

        {info && info.ready && (
          <section className="rounded-xl border border-accent/30 bg-accent/5 p-6 text-center space-y-4">
            <CheckCircle2 size={26} className="mx-auto text-emerald-400" />
            <h2 className="text-lg font-bold">Your design is ready{info.customer_name ? `, ${info.customer_name}` : ""}! ✨</h2>
            <p className="text-xs text-gray-400">Grab your files — web size for socials, Print HD (300-DPI) for the print shop.</p>
            <div className="flex gap-3 justify-center">
              <a href={dl("web")} download
                className="touch-manipulation flex items-center gap-2 rounded-xl border border-line px-4 py-2.5 text-xs font-semibold text-gray-200 hover:border-accent/50 transition">
                <Download size={13} /> Web PNG
              </a>
              <a href={dl("print")} download
                className="touch-manipulation flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-xs font-bold text-[#0b0f14] hover:brightness-110 transition">
                <Sparkles size={13} /> Print HD
              </a>
            </div>
          </section>
        )}

        <footer className="text-center text-[10px] text-gray-600 pt-2">
          Made with Mood AI · Accra
        </footer>
      </div>
    </main>
  );
}
