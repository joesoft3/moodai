import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Files",
  description: "Private file library and analysis workspace.",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
