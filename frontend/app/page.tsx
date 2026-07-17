import Link from "next/link";

const features: [string, string, string][] = [
  ["💬", "Streaming chat", "Grok-class models with a sharp, witty personality."],
  ["🌐", "Real-time search", "Live answers grounded in the web, news and X — with citations."],
  ["🧠", "Long-term memory", "Mood remembers what matters between conversations. You control it."],
  ["📄", "File intelligence", "Drop in PDFs, Word docs, spreadsheets or images and ask away."],
  ["🎤", "Voice mode", "Speak naturally and hear answers back — full voice conversations."],
  ["🖼️", "Image generation", "Describe it. Mood draws it."],
];

export default function Home() {
  return (
    <main className="min-h-screen flex flex-col items-center px-4 sm:px-6 py-14 sm:py-20">
      <div className="max-w-3xl text-center space-y-6">
        <span className="text-xs uppercase tracking-[0.3em] text-accent">Mood AI</span>
        <h1 className="text-[clamp(2.1rem,7vw,3.75rem)] font-bold leading-tight">
          A Grok-class AI, <span className="text-accent">built on your terms.</span>
        </h1>
        <p className="text-gray-400 text-lg">
          Chat, search, see, hear, and remember — one assistant powered by frontier models.
        </p>
        <div className="flex flex-wrap gap-3 justify-center pt-2">
          <Link
            href="/login"
            className="rounded-xl bg-accent text-black font-semibold px-6 py-3 hover:brightness-110 transition"
          >
            Get started
          </Link>
          <Link href="/chat" className="rounded-xl border border-line px-6 py-3 hover:bg-white/5 transition">
            Open app
          </Link>
        </div>
      </div>
      <div className="grid sm:grid-cols-2 md:grid-cols-3 gap-4 max-w-4xl 2xl:max-w-6xl mt-14 sm:mt-20">
        {features.map(([icon, title, desc]) => (
          <div key={title} className="bg-panel border border-line rounded-2xl p-5 space-y-2">
            <div className="text-2xl">{icon}</div>
            <h3 className="font-semibold">{title}</h3>
            <p className="text-sm text-gray-500">{desc}</p>
          </div>
        ))}
      </div>
    </main>
  );
}
