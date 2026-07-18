import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms of Service — Mood AI",
  description: "The agreement for using Mood AI apps, APIs and arenas.",
};

const SEC = [
  {
    t: "1 · The Service",
    b: [
      "Mood AI is an AI super-app: streaming chat (including ⚔️ Arena multi-model drafts, blind ballots and an AI judge verdict), 🧠 think mode with visible reasoning traces, live web search, long-term memory and cross-conversation recall, file & vision analysis, voice, image/video generation, plugin actions (Gmail, Calendar, GitHub) always staged for your approval, team workspaces, custom domains, usage metering and owner analytics.",
      "The Service orchestrates third-party AI providers (xAI/Grok, OpenAI, Google Gemini depending on configuration) plus hosting providers (Railway, Netlify). Third-party terms govern those layers.",
    ],
  },
  {
    t: "2 · Accounts",
    b: [
      "Provide accurate information, keep your password secret, and be at least 13 (16 in the EEA/UK). You are responsible for activity under your account. We may suspend accounts that breach these Terms.",
    ],
  },
  {
    t: "3 · Plans, usage & billing (when enabled)",
    b: [
      "Free and paid plans differ in limits (messages, arena runs, media quotas) shown in Settings → Usage; allowances reset as shown. Paid plans renew monthly via Stripe and can be cancelled any time — access lasts to the end of the paid period; prices may change with notice.",
    ],
  },
  {
    t: "4 · Acceptable use",
    b: [
      "Do not: break the law; involve minors or non-consensual or unauthorized personal data; probe, attack or burden the Service (including quota scraping or gate bypassing); reverse engineer beyond what law permits; upload malware; misrepresent AI output where disclosure is required; resell access without permission; make fully-automated decisions of legal significance about people without safeguards.",
    ],
  },
  {
    t: "5 · AI output — no advice",
    b: [
      "Answers are AI-generated and can be wrong, biased, incomplete or outdated — including thinking traces and Arena verdicts. Not medical, legal or financial advice; verify important answers independently.",
    ],
  },
  {
    t: "6 · Your content",
    b: [
      "You keep all rights to content you submit. You grant a limited, revocable license to process it solely to operate the Service for you (including sending relevant excerpts to the AI providers needed to answer). Don't submit others' data without a lawful basis. Memory and file embeddings live in your private store and can be cleared in Settings.",
    ],
  },
  {
    t: "7 · Plugins & approvals",
    b: [
      "Connected Gmail/Calendar/GitHub tokens are stored encrypted and used only to answer your requests and to stage write actions. Writes (send, schedule, label, file) execute only after your explicit Approve in the ✋ inbox; approvals expire in ~24h. Disconnect any time.",
    ],
  },
  {
    t: "8 · White-label arenas & teams",
    b: [
      "Domain operators may host branded arenas for their community; on those deployments the operator is the data controller for end-user interactions and we act as processor. Workspace owners manage members and shared conversations.",
    ],
  },
  {
    t: "9 · Intellectual property",
    b: [
      "The Service, code and brand are ours or our licensors'. Feedback may be used freely. You may reuse your own AI outputs subject to these Terms and model-provider terms.",
    ],
  },
  {
    t: "10 · Termination",
    b: [
      "Delete your account whenever (Settings). We may suspend for breach, risk or legal need with notice where practicable. Content deletion follows the Privacy Policy.",
    ],
  },
  {
    t: "11 · Disclaimers & liability",
    b: [
      "Provided “as is”, without warranties. To the extent law allows: no indirect/consequential liability; aggregate liability capped at the greater of US $100 or amounts paid in the prior 12 months. Nothing excludes liability that cannot be limited.",
    ],
  },
  {
    t: "12 · Changes",
    b: [
      "We may update these Terms with in-app or emailed notice of material changes; continued use accepts.",
    ],
  },
  {
    t: "13 · Governing law",
    b: [
      "Republic of Ghana law; Accra courts, unless mandatory consumer law requires otherwise.",
    ],
  },
  {
    t: "14 · Contact",
    b: [
      "Joesoft — Mood AI (Accra). Reach us via the owner address shown in-app or the GitHub repo (joesoft3/moodai).",
    ],
  },
];

export default function TermsPage() {
  return (
    <main className="min-h-screen bg-base text-gray-200">
      <div className="mx-auto max-w-3xl px-5 py-12">
        <p className="text-2xl font-bold">
          <span className="text-accent">✦</span> Mood AI
        </p>
        <h1 className="mt-6 text-3xl font-bold">Terms of Service</h1>
        <p className="mt-1 text-sm text-gray-500">
          Effective 18 July 2026 ·{" "}
          <a href="/privacy" className="text-accent underline">Privacy Policy →</a>
        </p>
        <p className="mt-6 text-[15px] leading-relaxed text-gray-300">
          These Terms are an agreement between you and the operator of Mood AI covering the apps,
          APIs, websites and connected arenas. By creating an account or using the Service you
          accept them.
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
          Source: <a className="underline" href="https://github.com/joesoft3/moodai/blob/main/docs/TERMS.md">docs/TERMS.md</a>
          {" "}· <a className="underline" href="/login">Back to sign in</a>
        </p>
      </div>
    </main>
  );
}
