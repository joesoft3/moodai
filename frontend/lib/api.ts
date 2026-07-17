export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export const token = {
  get(): string | null {
    return typeof window === "undefined" ? null : localStorage.getItem("mood_token");
  },
  set(t: string) {
    localStorage.setItem("mood_token", t);
  },
  clear() {
    localStorage.removeItem("mood_token");
  },
};

async function errorMessage(res: Response): Promise<string> {
  try {
    const j = await res.json();
    return typeof j.detail === "string" ? j.detail : JSON.stringify(j);
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}

/** Host of the page the user is on — lets the backend attribute per-domain analytics
 *  (the API itself is always reached on the platform's own host). */
function pageHost(): string | null {
  return typeof window === "undefined" ? null : window.location.host;
}

export async function apiFetch<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...((opts.headers as Record<string, string>) || {}) };
  if (!(opts.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const tk = token.get();
  if (tk) headers["Authorization"] = `Bearer ${tk}`;
  const ph = pageHost();
  if (ph) headers["X-Mood-Host"] = ph;
  const res = await fetch(`${API}${path}`, { ...opts, headers });
  if (!res.ok) throw new Error(await errorMessage(res));
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? res.json() : (res.blob() as any)) as Promise<T>;
}
