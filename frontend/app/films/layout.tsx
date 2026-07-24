import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Films",
  description: "Private AI films gallery for signed-in users.",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
