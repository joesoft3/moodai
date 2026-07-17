import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ConversationsProvider } from "@/lib/conversations";

export const metadata: Metadata = {
  title: "Mood AI",
  description: "Grok-class AI assistant — chat, live search, memory, voice, files and images.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.png", apple: "/icon.png" },
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "Mood AI" },
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
