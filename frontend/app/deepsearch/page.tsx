"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { apiFetch, token } from "@/lib/api";
import { LAST_CONV_KEY } from "@/lib/conversations";

type ResearchItem = { id: string; title: string; updated_at: string | null };

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export default function ResearchPage() {
  const router = useRouter();
  const [items, setItems] = useState<ResearchItem[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token.get()) {
      router.replace("/login");
      return;
    }
    apiFetch<{ items: ResearchItem[] }>("/deepsearch/research")
      .then((d) => setItems(d.items))
      .catch((e) => setError(e?.message || "Could not load research"));
  }, [router]);

  function openReport(id: string) {
    localStorage.setItem(LAST_CONV_KEY, id);
    router.push("/chat");
  }

  function fresh() {
    localStorage.removeItem(LAST_CONV_KEY);
    router.push("/chat");
  }

  return (
    <AppShell title="Research">
      <div className="mx-auto w-full max-w-3xl p-6 space-y-6">
        <div>
          <h1 className="text-2xl font-bold">
            🔭 Research library
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Every DeepSearch run lands here — re-open a report any time, sources included.
          </p>
        </div>

        <button
          onClick={fresh}
          className="rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-black hover:brightness-110 transition"
        >
          ＋ New research
        </button>
        <p className="text-[11px] text-gray-600 -mt-4">
          Opens a fresh chat — switch on <span className="text-accent">🔭 Deep</span> before sending.
        </p>

        {error && <p className="text-sm text-red-400">{error}</p>}

        {items === null && !error && (
          <div className="grid gap-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-20 animate-pulse rounded-2xl border border-line bg-surface" />
            ))}
          </div>
        )}

        {items && items.length === 0 && (
          <div className="rounded-2xl border border-line bg-surface p-8 text-center">
            <p className="text-3xl">🔭</p>
            <p className="mt-3 text-sm text-gray-400">
              No saved research yet. Ask a big question in chat with <span className="text-accent">🔭 Deep</span> on —
              the multi-round report (with 📚 sources) will appear here automatically.
            </p>
          </div>
        )}

        {items && items.length > 0 && (
          <div className="grid gap-3">
            {items.map((it) => (
              <button
                key={it.id}
                onClick={() => openReport(it.id)}
                className="group flex items-center justify-between gap-4 rounded-2xl border border-line bg-surface p-4 text-left transition hover:border-accent/50"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium text-gray-200">{it.title}</p>
                  <p className="mt-0.5 text-xs text-gray-600">🔭 DeepSearch report · {fmtDate(it.updated_at)}</p>
                </div>
                <span className="shrink-0 text-xs text-accent opacity-0 transition group-hover:opacity-100">
                  Open →
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
