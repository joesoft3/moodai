"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

/** 🌓 Black/white theme switch — persists to localStorage, no flash
 *  (layout.tsx applies the stored choice before first paint). */
export default function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  }, []);

  function toggle() {
    const next = theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("mood_theme", next);
    } catch {
      /* private mode — session-only theme */
    }
    setTheme(next);
  }

  if (compact) {
    return (
      <button
        onClick={toggle}
        aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
        title={theme === "light" ? "Dark theme" : "Light theme"}
        className="touch-manipulation p-2 text-gray-400 hover:text-gray-200 transition"
      >
        {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
      </button>
    );
  }

  return (
    <button
      onClick={toggle}
      className="touch-manipulation w-full flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-gray-400 hover:bg-white/5 hover:text-gray-200 transition"
      aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
    >
      {theme === "light" ? <Moon size={16} /> : <Sun size={16} />}
      {theme === "light" ? "Dark theme" : "Light theme"}
      <span className="ml-auto text-[10px] rounded-full border border-line px-2 py-0.5 text-gray-600">
        {theme === "light" ? "☀ on" : "● auto"}
      </span>
    </button>
  );
}
