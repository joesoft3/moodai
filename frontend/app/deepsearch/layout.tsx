import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Deep research",
  description: "Private deep research workspace for Mood AI.",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
