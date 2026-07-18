import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ConversationsProvider } from "@/lib/conversations";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: {
    default: "Mood AI — chat, arena, deep research & AI films with sound",
    template: "%s · Mood AI",
  },
  description:
    "A Grok-class AI super-app: streaming chat, multi-model ⚔ Arena, deep research with citations, " +
    "and a video studio that directs films with AI voiceovers and cinematic sound.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.png", apple: "/icon.png" },
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "Mood AI" },
  openGraph: {
    siteName: "Mood AI",
    type: "website",
    title: "Mood AI — chat, arena, deep research & AI films with sound",
    description:
      "Frontier models that debate blind in Arena, research with citations, and direct storyboard films with studio voiceovers — your chats, your terms.",
    images: [{ url: "/og.png", width: 1024, height: 500, alt: "Mood AI" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Mood AI",
    description: "A Grok-class AI super-app — arena debates, deep research, AI films with sound.",
    images: ["/og.png"],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover", // edge-to-edge on notched phones
  themeColor: "#0b0f14",
  // Resize the app when the on-screen keyboard opens (Chrome/Android),
  // so the composer and tab bar stay visible while typing.
  interactiveWidget: "resizes-content",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-base text-gray-100 antialiased">
        <ConversationsProvider>{children}</ConversationsProvider>
      </body>
    </html>
  );
}
