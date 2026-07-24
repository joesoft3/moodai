import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Delete your account — Mood AI",
  description:
    "How to permanently delete your Mood AI account and all associated data — in the app, on the web, or by request.",
  alternates: { canonical: "/account-deletion" },
};

const SEC = [
  {
    t: "Delete from the mobile app (Android / iOS)",
    b: [
      "Open the drawer (☰) → scroll to the bottom → tap “Delete account” (red).",
      "Read what is erased, type your password, and tap “Delete forever”.",
      "You are signed out immediately; the account and all data are erased at once.",
    ],
  },
  {
    t: "Delete on the web",
    b: [
      "Sign in → Settings → scroll to “Danger zone”.",
      "Choose “Delete my account…”, type your password, and confirm.",
      "Same effect, instant: everything below is purged in one pass.",
    ],
  },
  {
    t: "What gets deleted — immediately and permanently",
    b: [
      "Your profile (email, name, password hash) and plan/subscription record.",
      "All conversations and messages (including ones you posted in team chats), share links, and staged ✋ approvals.",
      "All uploads (files, images, audio, video) and the text extracted from them.",
      "Design Studio output: flyers, logos, banners, brand kits, batch sets, client order links.",
      "Films, Auto-Edit jobs, generated videos and their media files.",
      "Long-term memory and recall embeddings (vector store purge).",
      "Plugin connections (Gmail / Calendar / GitHub OAuth tokens).",
      "Push-device registrations and pending invitations you created.",
      "Teams you own are dissolved (memberships, invites, team conversations). Teams you only joined simply lose your membership.",
    ],
  },
  {
    t: "What may remain for a short time",
    b: [
      "Encrypted backups/log safety copies rotate out within ~30 days.",
      "Aggregated, de-identified usage counters (no email, no content) may persist for analytics.",
      "Provider-side processing at xAI/OpenAI/Google follows their own retention policies for API traffic.",
    ],
  },
  {
    t: "No password access?",
    b: [
      "Email support@moodaiapp.com from the account email with the subject “Delete my account”.",
      "We verify ownership and complete the deletion within 72 hours.",
    ],
  },
];

export default function AccountDeletionPage() {
  return (
    <main className="mx-auto max-w-2xl px-5 py-12 space-y-8">
      <div className="space-y-2">
        <p className="text-xs uppercase tracking-widest text-gray-500">Mood AI</p>
        <h1 className="text-3xl font-bold text-gray-100">Delete your account</h1>
        <p className="text-sm text-gray-400">
          Permanent self-service deletion — required by the Google Play and Apple App Store rules, in effect the moment you confirm.
        </p>
      </div>
      {SEC.map((s) => (
        <section key={s.t} className="space-y-2">
          <h2 className="text-lg font-semibold text-gray-200">{s.t}</h2>
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-gray-400">
            {s.b.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>
      ))}
      <p className="text-xs text-gray-600 border-t border-line pt-6">
        See also: <Link href="/privacy" className="text-accent underline underline-offset-2">Privacy Policy</Link> ·{" "}
        <Link href="/terms" className="text-accent underline underline-offset-2">Terms</Link> ·{" "}
        <Link href="/login" className="text-accent underline underline-offset-2">Sign in</Link>
      </p>
    </main>
  );
}
