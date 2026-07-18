import Link from "next/link";

const badges = ["S1 Mood-4", "⚔️ Arena v2", "🎙 Cinema Sound", "🔭 Deep Research", "🧠 Memory", "🔌 Plugins"];

const features: [string, string, string][] = [
  ["💬", "Streaming chat", "Frontier-grade models with a sharp, witty personality — Grok-class answers, your rules."],
  ["🎬", "Video with pure sound & voice", "Text-to-video with an AI voiceover in 10 voices and a cinematic ambient mix, loudness-polished by our ffmpeg studio."],
  ["⚔️", "Arena v2", "S1 Mood-4, GPT and Gemini debate blind. Ballots, judge verdicts, score cards — with one-tap rematch."],
  ["🔭", "Deep research", "Multi-source investigations with live citations and a saved research library."],
  ["🌐", "Real-time search", "Answers grounded in the live web, news and X — every claim cited."],
  ["🧠", "Long-term memory", "Mood remembers what matters between conversations. You stay in control."],
  ["📄", "File intelligence", "Drop in PDFs, Word docs, spreadsheets, images or video and ask away."],
  ["🎤", "Voice mode", "Speak naturally and hear answers back — full duplex voice conversations."],
  ["🔌", "Plugins", "Gmail, Calendar and GitHub with OAuth — Mood acts for you, with your approval."],
];

const steps: [string, string][] = [
  ["1", "Create your account — free, 30 seconds, no card."],
  ["2", "Chat, search, generate — images and sound-tracked video included."],
  ["3", "Take it anywhere — web app, Android app, your own custom domain."],
];

export default function Home() {
  return (
    <main className="min-h-screen flex flex-col">
      {/* Hero */}
      <section className="flex-1 flex flex-col items-center px-4 sm:px-6 pt-16 sm:pt-24 pb-12 relative overflow-hidden">
        <div
          aria-hidden
          className="absolute inset-x-0 top-0 h-[420px] pointer-events-none"
          style={{ background: "radial-gradient(600px 240px at 50% 0%, rgba(124,155,255,0.18), transparent 70%)" }}
        />
        <div className="relative max-w-3xl text-center space-y-6">
          <span className="text-xs uppercase tracking-[0.3em] text-accent">Mood AI</span>
          <h1 className="text-[clamp(2.2rem,7vw,3.9rem)] font-bold leading-[1.08]">
            A Grok-class AI that <span className="text-accent">talks back — in voice, video and sound.</span>
          </h1>
          <p className="text-gray-400 text-lg max-w-xl mx-auto">
            Chat, search, see, hear, remember — and now direct videos with AI voiceovers and a cinematic soundtrack.
            One assistant, your terms.
          </p>
          <div className="flex flex-wrap gap-2 justify-center">
            {badges.map((b) => (
              <span key={b} className="text-[11px] rounded-full border border-line bg-panel px-3 py-1 text-gray-400">
                {b}
              </span>
            ))}
          </div>
          <div className="flex flex-wrap gap-3 justify-center pt-2">
            <Link
              href="/login"
              className="rounded-xl bg-accent text-black font-semibold px-6 py-3 hover:brightness-110 transition"
            >
              Get started — free
            </Link>
            <Link href="/chat" className="rounded-xl border border-line px-6 py-3 hover:bg-white/5 transition">
              Open the app
            </Link>
          </div>
        </div>

        {/* Feature grid */}
        <div className="relative grid sm:grid-cols-2 md:grid-cols-3 gap-4 max-w-4xl 2xl:max-w-6xl mt-14 sm:mt-20 w-full">
          {features.map(([icon, title, desc]) => (
            <div key={title} className="bg-panel border border-line rounded-2xl p-5 space-y-2 hover:border-accent/40 transition">
              <div className="text-2xl">{icon}</div>
              <h3 className="font-semibold">{title}</h3>
              <p className="text-sm text-gray-500">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="border-t border-line px-4 sm:px-6 py-14">
        <div className="max-w-4xl 2xl:max-w-6xl mx-auto">
          <h2 className="text-center text-xl font-semibold mb-8">Up and running in three steps</h2>
          <div className="grid sm:grid-cols-3 gap-4">
            {steps.map(([n, text]) => (
              <div key={n} className="rounded-2xl border border-line bg-panel p-5 flex gap-3 items-start">
                <span className="rounded-full bg-accent/15 text-accent text-sm font-bold w-7 h-7 flex items-center justify-center shrink-0">
                  {n}
                </span>
                <p className="text-sm text-gray-400">{text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Get the app */}
      <section className="border-t border-line px-4 sm:px-6 py-14">
        <div className="max-w-4xl 2xl:max-w-6xl mx-auto rounded-3xl border border-line bg-panel p-8 sm:p-10 text-center space-y-5">
          <h2 className="text-xl sm:text-2xl font-semibold">Take Mood everywhere</h2>
          <p className="text-sm text-gray-400 max-w-lg mx-auto">
            The Android app brings push notifications for Arena verdicts and approvals, voice mode on the go, and the
            full studio in your pocket.
          </p>
          <div className="flex flex-wrap gap-3 justify-center">
            <a
              href="https://github.com/joesoft3/moodai/releases/latest"
              target="_blank"
              rel="noreferrer"
              className="rounded-xl bg-accent text-black font-semibold px-5 py-3 text-sm hover:brightness-110 transition flex items-center gap-2"
            >
              ⬇️ Android APK — latest release
            </a>
            <span className="rounded-xl border border-line px-5 py-3 text-sm text-gray-500 flex items-center gap-2">
              ▶️ Google Play — in review
            </span>
            <a
              href="https://github.com/joesoft3/moodai"
              target="_blank"
              rel="noreferrer"
              className="rounded-xl border border-line px-5 py-3 text-sm text-gray-300 hover:bg-white/5 transition"
            >
              ⭐ Star on GitHub
            </a>
          </div>
          <p className="text-[11px] text-gray-600">
            Free plan included. Add your own AI keys in Settings to unlock higher limits.
          </p>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-line px-4 sm:px-6 py-8">
        <div className="max-w-4xl 2xl:max-w-6xl mx-auto flex flex-wrap items-center gap-x-6 gap-y-3 text-xs text-gray-500">
          <span className="font-semibold text-gray-300">Mood AI</span>
          <span>© 2026 · Built with ❤️ in Accra</span>
          <span className="ml-auto flex gap-5">
            <Link href="/terms" className="hover:text-gray-300 transition">
              Terms of Service
            </Link>
            <Link href="/privacy" className="hover:text-gray-300 transition">
              Privacy Policy
            </Link>
            <Link href="/login" className="hover:text-gray-300 transition">
              Sign in
            </Link>
          </span>
        </div>
      </footer>
    </main>
  );
}
