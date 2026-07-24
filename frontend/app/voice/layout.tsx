import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Voice",
  description: "Private voice chat and transcription workspace.",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
