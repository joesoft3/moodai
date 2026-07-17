"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, token } from "@/lib/api";
import { BrandMark, useBrand } from "@/lib/brand";

const inputCls =
  "w-full rounded-xl bg-base border border-line px-4 py-2.5 text-sm outline-none focus:border-accent/60 placeholder-gray-600";

export default function LoginPage() {
  const router = useRouter();
  const brand = useBrand();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [appPassword, setAppPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await apiFetch<{ access_token: string }>(`/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify(
          mode === "register"
            ? {
                email,
                password,
                display_name: name || undefined,
                app_password: appPassword.trim() || undefined,
              }
            : { email, password }
        ),
      });
      token.set(res.access_token);
      // Returning from an invite-link bounce? Continue to the original destination.
      const next = new URLSearchParams(window.location.search).get("next");
      router.push(next && next.startsWith("/") ? next : "/chat");
    } catch (err: any) {
      setError(err.message ?? "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm bg-panel border border-line rounded-2xl p-8 space-y-6">
        <div className="text-center space-y-1">
          <h1 className="text-2xl font-bold flex items-center justify-center gap-2">
            <BrandMark brand={brand} /> {brand?.brand_name ?? "Mood AI"}
          </h1>
          {brand && <p className="text-[10px] text-gray-500">powered by Mood AI</p>}
          <p className="text-sm text-gray-500">
            {mode === "login" ? "Welcome back" : "Create your account — sign-up may be invite-only or require an access code"}
          </p>
        </div>
        <form onSubmit={submit} className="space-y-3">
          {mode === "register" && (
            <>
              <input className={inputCls} placeholder="Display name" value={name} onChange={(e) => setName(e.target.value)} />
              <input
                className={inputCls}
                type="text"
                autoComplete="off"
                placeholder="App access code (if this server requires one)"
                value={appPassword}
                onChange={(e) => setAppPassword(e.target.value)}
              />
            </>
          )}
          <input
            className={inputCls}
            type="email"
            required
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <input
            className={inputCls}
            type="password"
            required
            minLength={8}
            placeholder="Password (8+ chars)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <p className="text-sm text-red-400">{error}</p>}
          <button
            disabled={busy}
            className="w-full rounded-xl bg-accent text-black font-semibold py-2.5 disabled:opacity-40 hover:brightness-110 transition"
          >
            {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>
        <p className="text-xs text-center text-gray-500">
          {mode === "login" ? "No account? " : "Have an account? "}
          <button onClick={() => setMode(mode === "login" ? "register" : "login")} className="text-accent underline">
            {mode === "login" ? "Sign up" : "Sign in"}
          </button>
        </p>
      </div>
    </div>
  );
}
