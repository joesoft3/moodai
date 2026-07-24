import type { Metadata } from "next";
import OrderClient from "./OrderClient";

export const metadata: Metadata = {
  title: "Design order · Mood AI",
  description: "Order a flyer, logo or banner — delivered right back to this page.",
  robots: { index: false },
};

export default async function OrderPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <OrderClient token={token} />;
}
