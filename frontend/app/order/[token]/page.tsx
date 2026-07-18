import type { Metadata } from "next";
import OrderClient from "./OrderClient";

export const metadata: Metadata = {
  title: "Design order · Mood AI",
  description: "Order a flyer, logo or banner — delivered right back to this page.",
  robots: { index: false },
};

export default function OrderPage({ params }: { params: { token: string } }) {
  return <OrderClient token={params.token} />;
}
