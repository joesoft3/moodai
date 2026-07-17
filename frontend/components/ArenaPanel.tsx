"use client";

import { useState } from "react";
import { Crown, Shield, Swords, Wallet } from "lucide-react";
import type { ArenaState } from "./MessageBubble";

/** Arena events streamed from /agents/arena/stream. */
export interface ArenaEvt {
  type: string;
  topic?: string;
  brand?: string;   // 🌐 white-label arena brand (custom domains)
  judge?: string;   // ⚖️ judge label (platform default or white-label override)
  rematch?: boolean;
  round?: number;
  provider?: string;
  content?: string;
  vote?: string;
  rationale?: string;
  invalid?: boolean;
  warning?: string;
  winner?: string;
  drafts?: { provider: string; content: string; round: number }[];
  draft_order?: string[];
  votes?: { provider: string; ballot: { vote: string; rationale: string } | null; valid: boolean }[];
  usage?: Record<string, { in: number; out: number }>;
  message?: string;
}

const PROVIDER_STYLE: Record<string, { icon: string; chip: string }> = {
  "grok-code": { icon: "💻", chip: "bg-purple-400/10 border-purple-400/30 text-purple-300" },
  "gemini-2.5-flash": { icon: "⚡", chip: "bg-amber-400/10 border-amber-400/30 text-amber-300" },
  grok: { icon: "✦", chip: "bg-accent/10 border-accent/30 text-accent" },
  gpt: { icon: "🟢", chip: "bg-emerald-400/10 border-emerald-400/30 text-emerald-300" },
  gemini: { icon: "🔷", chip: "bg-sky-400/10 border-sky-400/30 text-sky-300" },
};

export function providerIcon(p: string): string {
  const key = Object.keys(PROVIDER_STYLE).find((k) => p.toLowerCase().includes(k));
  return key ? PROVIDER_STYLE[key].icon : "🤖";
}

export function ProviderChip({ p }: { p: string }) {
  const key = Object.keys(PROVIDER_STYLE).find((k) => p.toLowerCase().includes(k)) ?? "";
  const chip = PROVIDER_STYLE[key]?.chip ?? "bg-white/5 border-line text-gray-300";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${chip}`}>
      {providerIcon(p)} {p}
    </span>
  );
}

function UsageChips({ usage }: { usage: Record<string, { in: number; out: number }> }) {
  const entries = Object.entries(usage);
  if (!entries.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5 pt-1">
      <Wallet size={11} className="text-gray-600 mt-0.5" />
      {entries.map(([p, u]) => (
        <span key={p} className="text-[10px] text-gray-500 border border-line rounded-full px-2 py-0.5">
          {p}: {u.in}→{u.out} tok
        </span>
      ))}
    </div>
  );
}

/** ⚔️ Multi-model arena: drafts, blind ballots, Grok-4 verdict. Live or replayed. */
export default function ArenaPanel({ state, replayEvents }: { state?: ArenaState; replayEvents?: any[] }) {
  const [openDraft, setOpenDraft] = useState<string | null>(null);
  const events: any[] = replayEvents ?? state?.events ?? [];
  const verdict = events.find((e) => e.type === "arena_verdict") as ArenaEvt | undefined;
  const winner = verdict?.winner ?? state?.winner;
  const drafts = verdict?.drafts ?? state?.drafts ?? [];
  const draftOrder = verdict?.draft_order ?? state?.draftOrder ?? [];
  const votes = verdict?.votes ?? state?.votes ?? [];
  const usage = verdict?.usage ?? state?.usage ?? {};
  const live = !verdict && !state?.winner;

  const draftStarts = events.filter((e) => e.type === "draft_start");
  const draftDones = events.filter((e) => e.type === "draft_done");
  const voteCasts = events.filter((e) => e.type === "vote_cast");
  const topicEvt = events.find((e) => e.type === "topic") as ArenaEvt | undefined;
  const topic = topicEvt?.topic;
  const isRematch = (topicEvt as any)?.rematch === true;
  // 🌐 white-label: brand + judge come from the verdict (or persisted meta events)
  const arenaBrand =
    verdict?.brand ?? topicEvt?.brand ??
    ((state as any)?.events?.find((e: any) => e.type === "arena_verdict" && e.brand)?.brand || undefined);
  const judgeLabel =
    verdict?.judge ??
    ((state as any)?.events?.find((e: any) => e.type === "arena_verdict" && e.judge)?.judge || "Grok-4");
  const warnings = events.filter((e) => e.type === "warning");
  // live token streaming counters (draft_delta events as drafts generate)
  const liveChars: Record<string, number> = {};
  for (const e of events) {
    if (e.type === "draft_delta" && e.provider && typeof e.text === "string")
      liveChars[e.provider] = (liveChars[e.provider] ?? 0) + e.text.length;
  }

  const orderLabel = (i: number) => String.fromCharCode(65 + i); // A, B, C…
  const scores: Record<string, { accuracy?: number; clarity?: number }> =
    ((verdict as any)?.scores ?? ((state as any)?.events?.find((e: any) => e.type === "arena_verdict")?.scores) ?? {}) as any;
  const livesafe = (p?: string) => (p ? liveChars[p] ?? 0 : 0);
  const normVotes = votes.map((v) => ({
    provider: v.provider,
    vote: v.ballot?.vote ?? null,
    rationale: v.ballot?.rationale ?? "",
    valid: v.valid && !!v.ballot,
  }));

  return (
    <div className="mb-3 rounded-xl border border-accent/25 bg-accent/5 p-3 space-y-2.5">
      <p className="text-xs font-semibold text-accent flex items-center gap-1.5">
        <Swords size={13} /> {arenaBrand ? `${arenaBrand} · multi-model arena` : "Multi-model arena"}
        {live && <span className="text-gray-500 font-normal">— drafting & voting…</span>}
      </p>
      {topic && (
        <p className="text-[11px] text-gray-500 italic">
          {isRematch && <span className="not-italic text-accent font-semibold">🔁 REMATCH — beat the previous winner · </span>}
          “{topic}”
        </p>
      )}

      {/* live progress (drafts stream token-by-token) */}
      {live && (
        <div className="space-y-1 text-[11px] text-gray-400">
          {draftStarts.map((e, i) => {
            const done = draftDones.some((d) => d.provider === e.provider && d.round === e.round);
            const chars = livesafe(e.provider);
            return (
              <p key={i}>
                {done ? "✅" : "⏳"} {providerIcon(e.provider ?? "")} {e.provider}{" "}
                {done ? "drafted" : chars > 0 ? `drafting… ${chars.toLocaleString()} chars` : "drafting…"}
              </p>
            );
          })}
          {voteCasts.map((e, i) => (
            <p key={`v${i}`}>
              {e.invalid ? "⚠️" : "🗳️"} {providerIcon(e.provider ?? "")} {e.provider} voted{" "}
              {e.invalid ? "(invalid ballot)" : `for ${e.vote}`}
            </p>
          ))}
        </div>
      )}

      {warnings.map((w, i) => (
        <p key={i} className="text-[11px] text-yellow-500">
          ⚠️ {w.message ?? w.warning}
        </p>
      ))}

      {/* verdict */}
      {(winner || !live) && winner && (
        <div className="rounded-lg bg-accent/10 border border-accent/30 px-3 py-2 text-xs text-accent font-semibold flex items-center gap-1.5">
          <Crown size={13} /> {judgeLabel} verdict: {winner}
          <span className="text-gray-500 font-normal">
            · {normVotes.filter((v) => v.valid).length}/{normVotes.length} valid ballots
          </span>
        </div>
      )}

      {/* ballots */}
      {normVotes.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[11px] font-medium text-gray-400 flex items-center gap-1">
            <Shield size={11} /> Blind ballots
          </p>
          {normVotes.map((v, i) => (
            <div key={i} className="flex items-start gap-2 text-[11px]">
              <ProviderChip p={v.provider} />
              <span className={`flex-1 ${v.valid ? "text-gray-400" : "text-yellow-500/80"}`}>
                {v.valid ? (
                  <>
                    → <span className="text-gray-200 font-medium">{v.vote}</span>
                    {v.rationale && <span className="text-gray-500"> — {v.rationale}</span>}
                  </>
                ) : (
                  "ballot invalid / missing"
                )}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* drafts (expandable) */}
      {drafts.length > 0 && (
        <div className="space-y-1">
          <p className="text-[11px] font-medium text-gray-400">Drafts (blind order {draftOrder.map((_, i) => orderLabel(i)).join(" · ")})</p>
          {draftOrder.map((label, i) => {
            const d = drafts[i];
            if (!d) return null;
            const open = openDraft === label;
            return (
              <div key={label} className="rounded-lg bg-base border border-line">
                <button
                  onClick={() => setOpenDraft(open ? null : label)}
                  className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[11px] text-gray-300 hover:text-white transition"
                >
                  <span className="font-bold text-gray-500">{label}</span>
                  <ProviderChip p={d.provider} />
                  {winner && d.provider === winner && <Crown size={11} className="text-accent" />}
                  {scores[label] && (
                    <span className="flex gap-1 ml-1">
                      <span className="rounded-full bg-white/5 border border-line px-1.5 py-0.5 text-[9.5px] text-gray-500" title="Judge accuracy score">
                        🎯 {scores[label].accuracy ?? "–"}
                      </span>
                      <span className="rounded-full bg-white/5 border border-line px-1.5 py-0.5 text-[9.5px] text-gray-500" title="Judge clarity score">
                        ✍ {scores[label].clarity ?? "–"}
                      </span>
                    </span>
                  )}
                  <span className="ml-auto text-gray-600">{open ? "hide" : "view"}</span>
                </button>
                {open && (
                  <p className="px-2.5 pb-2 text-[11px] text-gray-400 whitespace-pre-wrap max-h-40 overflow-y-auto scrollbar-thin border-t border-line pt-1.5">
                    {d.content}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}

      <UsageChips usage={usage} />
    </div>
  );
}
