import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Owner panel",
  description: "Private owner administration area for Mood AI.",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
