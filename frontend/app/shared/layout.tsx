import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Shared conversation",
  description: "Read-only shared conversation snapshot.",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
