"use client";

import { API, token } from "./api";

/** Shared SSE wire contract for every streaming surface (chat, agents, deepsearch). */
export interface ChatPayload {
  conversation_id: string | null;
  workspace_id?: string | null;
  message: string;
  files: string[];
  search: boolean;
  plugins?: boolean;
  regenerate?: boolean;
  depth?: string;
  model?: string;       // premium picker: grok-4 | auto | grok-4-fast | grok-3-mini
  think?: boolean;      // extended reasoning (grok-4 / grok-code-fast-1 only)
  arena?: boolean;      // ⚔️ multi-model arena: providers debate, -4 judges
  arena_extra?: string; // extra provider (grok-code-fast-1 | gemini-2.5-flash) when keys exist
  rematch?: boolean;    // ⚔️ rematch — drafters try to beat the previous winner
}

export interface ChatEvent {
  type: string;
  text?: string;
  message?: string;
  conversation_id?: string;
  model?: string;
  provider?: string;
  citations?: string[];
  created?: boolean;
  // plugin tool events
  calls?: { name: string; ok: boolean }[];
  // human-in-the-loop: staged write actions to approve/reject
  actions?: { id: string; name: string; args: Record<string, any> }[];
  // multi-agent events
  steps?: { agent: string; task: string }[];
  i?: number; // step index (steps may run concurrently / repeat an agent)
  agent?: string;
  task?: string;
  preview?: string;
  // deepsearch events
  subtopics?: string[];
  round?: number;
  total?: number;
  query?: string;
  sources?: number;
  note?: string;
  // 🧠 extended-reasoning events (grok-4 / grok-code-fast-1)
  trace?: string; // thinking delta (reasoning_content)
  thinking?: { summary?: string | null }; // final thinking event
  think_time_ms?: number;
  // ⚔️ arena events
  topic?: string;
  rematch?: boolean;
  brand?: string;   // 🌐 white-label arena brand (custom domains)
  judge?: string;   // ⚖️ judge label (platform default or white-label)
  draft_start?: { round: number; provider: string };
  draft_delta?: { provider: string; text: string };
  draft_done?: { round: number; provider: string; content: string };
  vote_start?: { provider: string };
  vote_cast?: { provider: string; vote: string; rationale: string; invalid?: boolean };
  winner?: string;
  drafts?: { provider: string; content: string; round: number; slot?: string }[];
  draft_order?: string[];
  scores?: Record<string, { accuracy?: number; clarity?: number }>;
  votes?: { provider: string; ballot: { vote: string; rationale: string } | null; valid: boolean }[];
  warning?: string;
  usage?: Record<string, { in: number; out: number }>;
  error_code?: string;
}

async function sseErrorMessage(res: Response): Promise<string> {
  try {
    const j = await res.json();
    return typeof j.detail === "string" ? j.detail : JSON.stringify(j);
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}

/**
 * POST + incremental SSE parsing (EventSource can't POST or authorize).
 * One implementation shared by everything that streams — with auto-retry on
 * network drops mid-stream? No: generators are not idempotent, so callers own
 * retry policy; `signal` powers "stop generating".
 */
async function* streamSSE(
  endpoint: string,
  payload: unknown,
  signal?: AbortSignal,
  timeoutMs = 6 * 60_000,
): AsyncGenerator<ChatEvent> {
  const tk = token.get();
  let res: Response;
  try {
    res = await fetch(`${API}${endpoint}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(tk ? { Authorization: `Bearer ${tk}` } : {}),
      ...(typeof window !== "undefined" ? { "X-Mood-Host": window.location.host } : {}),
    },
      body: JSON.stringify(payload),
      signal: signal ?? AbortSignal.timeout(timeoutMs),
    });
  } catch (e) {
    if (e instanceof TypeError) {
      throw new Error("Can't reach the Mood AI server — it may be starting up or your connection dropped. Try again in a few seconds.");
    }
    throw e;
  }
  if (!res.ok || !res.body) throw new Error(await sseErrorMessage(res));

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const chunks = buf.split("\n\n");
    buf = chunks.pop() ?? "";
    for (const raw of chunks) {
      const line = raw.trim();
      if (!line.startsWith("data:")) continue;
      try {
        yield JSON.parse(line.slice(5).trim()) as ChatEvent;
      } catch {
        /* ignore malformed event */
      }
    }
  }
}

/** Standard chat stream (also the base for agent/deepsearch streams). */
export async function streamChat(
  payload: ChatPayload,
  onEvent: (e: ChatEvent) => void,
  endpoint = "/chat/stream",
  signal?: AbortSignal
): Promise<void> {
  for await (const ev of streamSSE(endpoint, payload, signal)) onEvent(ev);
}

/** Async-iterable variant — cleaner control flow for new code. */
export function streamEvents(
  endpoint: string,
  payload: unknown,
  signal?: AbortSignal
): AsyncGenerator<ChatEvent> {
  return streamSSE(endpoint, payload, signal);
}

/** Fire-and-forget wrapper that swallows nothing — errors route into onEvent as
 *  a synthetic `error` event so UI states stay uniform. */
export async function onEvent(
  endpoint: string,
  payload: unknown,
  handler: (e: ChatEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  try {
    for await (const ev of streamSSE(endpoint, payload, signal)) handler(ev);
  } catch (err: any) {
    handler({ type: "error", message: err?.message ?? "stream failed" });
  }
}
