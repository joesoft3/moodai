"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { apiFetch, token } from "./api";

export interface ConvItem {
  id: string;
  title: string;
}

/** Where the last open conversation id is remembered across sessions/reloads. */
export const LAST_CONV_KEY = "mood.lastConvId";

interface CtxType {
  convs: ConvItem[];
  activeId: string | null;
  setActiveId: (id: string | null) => void;
  refresh: () => Promise<void>;
  remove: (id: string) => Promise<void>;
}

const Ctx = createContext<CtxType | null>(null);

export function useConversations(): CtxType {
  const c = useContext(Ctx);
  if (!c) throw new Error("useConversations must be used inside ConversationsProvider");
  return c;
}

export function ConversationsProvider({ children }: { children: React.ReactNode }) {
  const [convs, setConvs] = useState<ConvItem[]>([]);
  const [activeIdState, setActiveIdState] = useState<string | null>(null);
  const pathname = usePathname();

  // Selecting a conversation remembers it across reloads; clearing (new chat) forgets it
  const setActiveId = useCallback((id: string | null) => {
    setActiveIdState(id);
    try {
      if (id) localStorage.setItem(LAST_CONV_KEY, id);
      else localStorage.removeItem(LAST_CONV_KEY);
    } catch {
      /* storage unavailable */
    }
  }, []);
  const activeId = activeIdState;

  const refresh = useCallback(async () => {
    if (!token.get()) return;
    try {
      setConvs(await apiFetch<ConvItem[]>("/conversations"));
    } catch {
      /* not logged in yet / api down */
    }
  }, []);

  // Refetch on every route change so the list is fresh after login/navigation
  useEffect(() => {
    void refresh();
  }, [refresh, pathname]);

  const remove = useCallback(async (id: string) => {
    setConvs((c) => c.filter((x) => x.id !== id));
    setActiveIdState((curr) => {
      const next = curr === id ? null : curr;
      try {
        if (next) localStorage.setItem(LAST_CONV_KEY, next);
        else localStorage.removeItem(LAST_CONV_KEY);
      } catch {
        /* storage unavailable */
      }
      return next;
    });
    try {
      await apiFetch(`/conversations/${id}`, { method: "DELETE" });
    } catch {
      /* ignore */
    }
  }, []);

  return (
    <Ctx.Provider value={{ convs, activeId, setActiveId, refresh, remove }}>{children}</Ctx.Provider>
  );
}
