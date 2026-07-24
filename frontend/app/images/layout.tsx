import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Images",
  description: "Private image and video generation workspace.",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
