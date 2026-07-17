"use client";

import { useState } from "react";
import { MessageSquare, Plus, Trash2 } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { useConversations } from "@/lib/conversations";

/** Conversation history list — used by both the desktop sidebar and mobile/tablet drawer.
 *  Double-click (or long-press) a title to rename it inline. */
export default function ConversationList({ onNavigate }: { onNavigate?: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const { convs, activeId, setActiveId, remove, refresh } = useConversations();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  function go(fn: () => void) {
    fn();
    onNavigate?.();
    if (pathname !== "/chat") router.push("/chat");
  }

  function startRename(c: { id: string; title: string }) {
    setEditingId(c.id);
    setEditText(c.title);
  }

  async function commitRename(id: string) {
    const title = editText.trim();
    setEditingId(null);
    if (!title) return;
    try {
      await apiFetch(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify({ title }) });
      await refresh();
    } catch (e) {
      console.error(e);
    }
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="p-3">
        <button
          onClick={() => go(() => setActiveId(null))}
          className="w-full flex items-center gap-2 rounded-xl bg-accent/15 hover:bg-accent/25 border border-accent/30 px-4 py-2.5 text-sm font-medium transition"
        >
          <Plus size={16} /> New chat
        </button>
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin px-2 pb-2 space-y-1">
        {convs.map((c) => (
          <div
            key={c.id}
            onClick={() => editingId !== c.id && go(() => setActiveId(c.id))}
            onDoubleClick={() => startRename(c)}
            className={`group flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm cursor-pointer ${
              activeId === c.id ? "bg-accent/15 text-white" : "text-gray-400 hover:bg-white/5"
            }`}
          >
            <MessageSquare size={14} className="shrink-0 opacity-60" />
            {editingId === c.id ? (
              <input
                autoFocus
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                onBlur={() => commitRename(c.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitRename(c.id);
                  if (e.key === "Escape") setEditingId(null);
                }}
                onClick={(e) => e.stopPropagation()}
                className="flex-1 min-w-0 bg-base border border-accent/40 rounded-md px-2 py-0.5 text-sm outline-none"
              />
            ) : (
              <span className="flex-1 truncate" title="Double-click to rename">
                {c.title || "New chat"}
              </span>
            )}
            <button
              onClick={(e) => {
                e.stopPropagation();
                remove(c.id);
              }}
              className="md:opacity-0 md:group-hover:opacity-100 text-gray-500 hover:text-red-400 transition"
              aria-label="Delete chat"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        {convs.length === 0 && <p className="text-xs text-gray-600 px-3 py-4">No conversations yet.</p>}
      </div>
    </div>
  );
}
