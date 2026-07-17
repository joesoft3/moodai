"use client";

import { useEffect, useState } from "react";
import { API } from "./api";

/** White-label brand for the current host (served for ACTIVE custom domains). */
export interface Brand {
  brand_name: string;
  domain: string;
  accent?: string | null;
  logo_data?: string | null;
  workspace_id?: string | null;
}

/** Runtime re-theme: override the compiled accent Tailwind classes with the
 *  domain owner's brand color (injected stylesheet beats same-specificity rules). */
export function applyAccent(hex: string) {
  let el = document.getElementById("mood-brand") as HTMLStyleElement | null;
  if (!el) {
    el = document.createElement("style");
    el.id = "mood-brand";
    document.head.appendChild(el);
  }
  el.textContent =
    `.text-accent{color:${hex}!important}` +
    `.bg-accent{background-color:${hex}!important}` +
    `.bg-accent\\/5{background-color:${hex}0d!important}` +
    `.bg-accent\\/10{background-color:${hex}1a!important}` +
    `.bg-accent\\/15{background-color:${hex}26!important}` +
    `.bg-accent\\/20{background-color:${hex}33!important}` +
    `.bg-accent\\/70{background-color:${hex}b3!important}` +
    `.hover\\:bg-accent:hover{background-color:${hex}!important}` +
    `.border-accent\\/30{border-color:${hex}4d!important}` +
    `.border-accent\\/40{border-color:${hex}66!important}` +
    `.border-accent\\/50{border-color:${hex}80!important}` +
    `.focus\\:border-accent\\/60:focus{border-color:${hex}99!important}`;
}

export function applyFavicon(dataUrl: string) {
  let link = document.querySelector("link[rel~='icon']") as HTMLLinkElement | null;
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  link.href = dataUrl;
}

/**
 * Fetch + auto-apply the white-label brand for the current host (accent + favicon).
 * No-op on localhost/platform hosts. Pages set their own document.title.
 */
export function useBrand(): Brand | null {
  const [brand, setBrand] = useState<Brand | null>(null);
  useEffect(() => {
    const host = window.location.host;
    if (/localhost|127\.0\.0\.1/.test(host)) return;
    fetch(`${API}/domains/by-host?host=${encodeURIComponent(host)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => {
        if (b?.brand_name) {
          setBrand(b);
          if (b.accent) applyAccent(b.accent);
          if (b.logo_data) applyFavicon(b.logo_data);
        }
      })
      .catch(() => {});
  }, []);
  return brand;
}

/** Logo img when the brand has one, else the ✦ mark. */
export function BrandMark({ brand, size = "h-7 w-7" }: { brand: Brand | null; size?: string }) {
  if (brand?.logo_data) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={brand.logo_data} alt={brand.brand_name} className={`${size} rounded-md object-contain shrink-0`} />;
  }
  return <span className="text-accent text-lg leading-none shrink-0">✦</span>;
}

export const DEFAULT_BRAND_NAME = "Mood AI";
