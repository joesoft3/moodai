"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, token } from "@/lib/api";
import { BrandMark, useBrand } from "@/lib/brand";

/**
 * Redeems a workspace invite link: /join/<token>
 * - Not signed in → bounced to /login?next=/join/<token> and returns here after auth
 * - Domain-gated teams: the backend rejects accounts whose email isn't on the bound domain
 * - White-labeled when opened on a verified custom domain
 */
export default function JoinPage({ params }: { params: { token: string } }) {
  const router = useRouter();
  const brand = useBrand();
  const [state, setState] = useState<{
    phase: "working" | "ok" | "err";
    msg?: string;
    ws?: { id: string; name: string };
  }>({ phase: "working" });

  useEffect(() => {
    if (!token.get()) {
      router.replace(`/login?next=${encodeURIComponent(`/join/${params.token}`)}`);
      return;
    }
    apiFetch<{ workspace: { id: string; name: string }; already_member?: boolean }>("/workspaces/join", {
      method: "POST",
      body: JSON.stringify({ token: params.token }),
    })
      .then((j) =>
        setState({
          phase: "ok",
          ws: j.workspace,
          msg: j.already_member ? "You're already a member — welcome back." : "✅ You've joined the team!",
        })
      )
      .catch((e: any) => setState({ phase: "err", msg: e.message ?? "This invite couldn't be used." }));
  }, [params.token, router]);

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm bg-panel border border-line rounded-2xl p-8 space-y-5 text-center">
        <h1 className="text-xl font-bold flex items-center justify-center gap-2">
          <BrandMark brand={brand} /> {brand?.brand_name ?? "Mood AI"} · Team invite
        </h1>
        {brand && <p className="text-[10px] text-gray-500 -mt-3">powered by Mood AI</p>}
        {state.phase === "working" && (
          <p className="text-sm text-gray-500 animate-pulse">Redeeming your invite…</p>
        )}
        {state.phase === "ok" && state.ws && (
          <>
            <p className="text-sm text-gray-300">{state.msg}</p>
            <p className="text-lg font-semibold text-gray-100">👥 {state.ws.name}</p>
            <button
              onClick={() => router.push(`/chat?ws=${state.ws!.id}`)}
              className="w-full rounded-xl bg-accent text-black font-semibold py-2.5 hover:brightness-110 transition"
            >
              Open team chat →
            </button>
          </>
        )}
        {state.phase === "err" && (
          <>
            <p className="text-sm text-red-400">{state.msg}</p>
            <button
              onClick={() => router.push("/chat")}
              className="w-full rounded-xl bg-white/10 text-gray-200 font-semibold py-2.5 hover:bg-white/20 transition"
            >
              Go to my chats
            </button>
          </>
        )}
      </div>
    </div>
  );
}
