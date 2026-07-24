import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Design Studio",
  description: "Private AI design studio for signed-in users.",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
