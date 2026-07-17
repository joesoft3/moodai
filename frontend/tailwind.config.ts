import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    // Full tier ladder: tiny phones (xs) → phones (sm) → tablets (md) →
    // laptops (lg) → desktops (xl) → large monitors (2xl) → ultrawide (3xl)
    screens: {
      xs: "360px",
      sm: "640px",
      md: "768px",
      lg: "1024px",
      xl: "1280px",
      "2xl": "1536px",
      "3xl": "1920px",
    },
    extend: {
      colors: {
        base: "#0b0f14",
        panel: "#12181f",
        line: "#1e293b",
        accent: "#7c9bff",
      },
    },
  },
  plugins: [],
};

export default config;
