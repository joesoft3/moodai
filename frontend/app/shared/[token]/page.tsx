"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { API } from "@/lib/api";
import { BrandMark, useBrand } from "@/lib/brand";

interface SharedMsg {
  role: string;
  content: string;
  created_at: string | null;
}

interface SharedData {
  title: string;
  updated_at: string | null;
  messages: SharedMsg[];
}

/** Public, login-free view of a conversation shared via /conversations/{id}/share.
 *  White-labeled when opened on a verified custom domain (name/logo/accent). */
export default function SharedConversationPage() {
  const params = useParams<{ token: string | string[] }>();
  const shareToken = useMemo(() => {
    const raw = params?.token;
    return Array.isArray(raw) ? raw[0] ?? "" : raw ?? "";
  }, [params]);
  const [data, setData] = useState<SharedData | null>(null);
  const [error, setError] = useState("");
  const brand = useBrand();

  useEffect(() => {
    if (!shareToken) return;
    // plain fetch — this page is unauthenticated by design
    fetch(`${API}/share/${shareToken}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 404 ? "This shared link is invalid or has been revoked." : `Error ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message ?? "Could not load this shared conversation."));
  }, [shareToken]);

  useEffect(() => {
    if (data) document.title = `${data.title} · ${brand?.brand_name ?? "Mood AI"}`;
  }, [data, brand]);

  return (
    <div className="min-h-screen bg-base text-gray-200">
      <header className="sticky top-0 z-10 border-b border-line bg-panel/90 backdrop-blur">
        <div className="max-w-3xl mx-auto px-4 py-3 flex items-center gap-2">
          <BrandMark brand={brand} />
          <span className="font-semibold text-sm truncate">{data?.title ?? "Shared conversation"}</span>
          <span className="text-[11px] text-gray-500 ml-auto shrink-0">
            shared via {brand?.brand_name ?? "Mood AI"}
          </span>
        </div>
      </header>
      <main className="max-w-3xl mx-auto px-4 py-8 space-y-6">
        {error && (
          <div className="rounded-xl border border-red-400/30 bg-red-400/10 text-red-300 text-sm px-4 py-6 text-center">
            🔗 {error}
          </div>
        )}
        {!data && !error && <p className="text-center text-gray-500 text-sm mt-16">Loading shared conversation…</p>}
        {data?.messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="bg-accent/20 border border-accent/30 rounded-2xl px-4 py-3 max-w-[85%] whitespace-pre-wrap [overflow-wrap:anywhere] text-sm">
                {m.content}
              </div>
            </div>
          ) : (
            <div key={i} className="text-[15px] leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
            </div>
          )
        )}
        {data && (
          <p className="text-center text-[11px] text-gray-600 pt-6">
            Read-only snapshot · links can be revoked by the owner at any time
          </p>
        )}
      </main>
    </div>
  );
}
