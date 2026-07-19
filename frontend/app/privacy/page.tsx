import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy Policy — Mood AI",
  description: "What Mood AI collects, why, and your choices. Short version: your chats belong to you.",
};

const SEC = [
  {
    t: "What we collect",
    b: [
      "Account: email, display name, password hash — for auth and plans.",
      "Conversations & memory: your messages, assistant replies, thinking traces, memory facts you let it keep, recall embeddings — to provide chat and cross-conversation recall.",
      "Uploads: documents, images, audio/video — text extraction, analysis, embeddings in your private collection.",
      "Plugin tokens: Gmail/Calendar/GitHub OAuth tokens — stored encrypted (Fernet), used only to answer requests and stage actions you approve. Revocable any time.",
      "Arena & usage telemetry: counts, tokens, model mix, votes — metering, quotas, aggregated owner analytics, abuse prevention.",
      "Operational logs: IP, timing, errors — security & debugging, short retention.",
      "Billing (when enabled) is handled by Stripe; we store plan status only, never card numbers.",
    ],
  },
  {
    t: "How we use it",
    b: [
      "Running the Service — your content is sent to the configured AI providers (xAI/Grok, OpenAI, Google Gemini) needed to respond — plus remembering preferences, enforcing quotas, securing accounts, aggregated analytics, support, and legal compliance. We do not sell personal data, do not train our own models on your content, and show no third-party ads.",
    ],
  },
  {
    t: "Sharing & processors",
    b: [
      "AI providers (xAI, OpenAI, Google) receive the conversation context needed to answer. Hosting: Railway, Netlify, Qdrant, Redis, Stripe, GitHub. On white-label customer arenas the domain operator is the data controller for their end-users — see their notice. Legal disclosure only when required or to defend safety.",
    ],
  },
  {
    t: "Retention & deletion",
    b: [
      "Conversations, uploads and memory persist until you delete them or your account. Deletions purge embeddings promptly; account deletion is instant and self-service (Settings → Danger zone or the app drawer — see /account-deletion) and clears remaining data; backups rotate within ~30 days. Aggregated, de-identified usage totals may persist. Plugin tokens are erased on disconnect.",
    ],
  },
  {
    t: "Security",
    b: [
      "TLS in transit, encryption at rest, PBKDF2-hashed passwords, human-in-the-loop approval before any external write, owner-only admin surfaces. Report issues via GitHub or the in-app channel.",
    ],
  },
  {
    t: "Your rights",
    b: [
      "Access, export, rectification, deletion, restriction, objection and portability where applicable; withdraw consent for plugins/memory any time — Settings manages memory, files and connections directly. Complaints may go to your local data-protection authority.",
    ],
  },
  {
    t: "Children",
    b: [
      "Not for children under 13 (16 in the EEA/UK); such accounts are closed on notice.",
    ],
  },
  {
    t: "International transfers",
    b: [
      "Processing happens wherever providers operate (US/EU/…) using their contractual safeguards.",
    ],
  },
  {
    t: "Cookies & storage",
    b: [
      "Sign-in uses a local-storage token; no ad cookies, no third-party trackers.",
    ],
  },
  {
    t: "Changes",
    b: [
      "Material changes announced in-app/email; history lives beside this doc in the repository.",
    ],
  },
  {
    t: "Contact / data controller",
    b: [
      "Joesoft — Mood AI (Accra, Ghana): the in-app channel or the GitHub repo. On white-label deployments, contact the domain operator first.",
    ],
  },
];

export default function PrivacyPage() {
  return (
    <main className="min-h-screen bg-base text-gray-200">
      <div className="mx-auto max-w-3xl px-5 py-12">
        <p className="text-2xl font-bold">
          <span className="text-accent">✦</span> Mood AI
        </p>
        <h1 className="mt-6 text-3xl font-bold">Privacy Policy</h1>
        <p className="mt-1 text-sm text-gray-500">
          Effective 18 July 2026 ·{" "}
          <a href="/terms" className="text-accent underline">Terms of Service →</a>
        </p>
        <p className="mt-6 rounded-xl border border-accent/30 bg-accent/10 px-4 py-3 text-[15px] text-accent">
          Short version: your chats belong to you. Plugins always ask before acting. You can delete everything.
        </p>
        {SEC.map((s) => (
          <section key={s.t} className="mt-8">
            <h2 className="text-lg font-semibold text-accent">{s.t}</h2>
            {s.b.map((p) => (
              <p key={p.slice(0, 24)} className="mt-2 text-[15px] leading-relaxed text-gray-300">
                {p}
              </p>
            ))}
          </section>
        ))}
        <p className="mt-12 border-t border-line pt-6 text-xs text-gray-600">
          Source: <a className="underline" href="https://github.com/joesoft3/moodai/blob/main/docs/PRIVACY.md">docs/PRIVACY.md</a>
          {" "}· <a className="underline" href="/login">Back to sign in</a>
        </p>
      </div>
    </main>
  );
}
