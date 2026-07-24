import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  const base = (process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000").replace(/\/+$/, "");
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/privacy", "/terms", "/account-deletion", "/f/"],
        disallow: [
          "/admin",
          "/chat",
          "/deepsearch",
          "/design",
          "/files",
          "/films",
          "/images",
          "/join/",
          "/login",
          "/order/",
          "/plugins",
          "/settings",
          "/shared/",
          "/voice",
        ],
      },
    ],
    sitemap: `${base}/sitemap.xml`,
    host: base,
  };
}
