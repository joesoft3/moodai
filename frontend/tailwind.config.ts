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
        // Theme tokens live in globals.css (dark :root, [data-theme="light"] light) —
        // components never change when the user flips black/white themes.
        base: "rgb(var(--mood-base) / <alpha-value>)",
        panel: "rgb(var(--mood-panel) / <alpha-value>)",
        line: "rgb(var(--mood-line) / <alpha-value>)",
        accent: "rgb(var(--mood-accent) / <alpha-value>)",
      },
    },
  },
  plugins: [],
};

export default config;
