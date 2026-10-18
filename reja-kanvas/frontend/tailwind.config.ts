import type { Config } from "tailwindcss";

const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Theme tokens live in globals.css as RGB triplets so light/dark swap in one place.
        paper: { DEFAULT: v("paper"), 2: v("paper-2"), 3: v("paper-3") },
        line: { DEFAULT: v("line"), soft: v("line-soft"), strong: v("line-strong") },
        ink: { DEFAULT: v("ink"), 2: v("ink-2"), 3: v("ink-3"), muted: v("ink-muted") },
        surface: v("surface"),
        accent: { DEFAULT: v("accent"), ink: v("accent-ink"), soft: v("accent-soft") },
        warn: { DEFAULT: v("warn"), ink: v("warn-ink"), soft: v("warn-soft"), strong: v("warn-strong") },
        ok: { DEFAULT: v("ok"), ink: v("ok-ink"), soft: v("ok-soft") },
        chart: { 1: v("chart-1"), 2: v("chart-2") },
        card: {
          yellow: "#FFF1BF",
          mint: "#DDF2E3",
          lilac: "#E7E2FF",
          peach: "#FFE3D3",
          sky: "#E4EAFF",
          white: "#FFFFFF",
        },
      },
      fontFamily: {
        display: ["var(--font-display)", "system-ui", "sans-serif"],
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 0 rgba(27,29,34,.06), 0 10px 24px -14px rgba(27,29,34,.35)",
        lift: "0 30px 50px -20px rgba(27,29,34,.45), 0 0 0 1px rgba(27,29,34,.04)",
        paper: "0 1px 2px rgba(27,29,34,.08), 0 24px 48px -28px rgba(27,29,34,.35)",
      },
      keyframes: {
        stamp: {
          "0%": { transform: "rotate(-12deg) scale(2.2)", opacity: "0" },
          "60%": { transform: "rotate(-12deg) scale(.92)", opacity: "1" },
          "100%": { transform: "rotate(-12deg) scale(1)", opacity: "1" },
        },
        pulsering: {
          "0%": { boxShadow: "0 0 0 0 rgba(43,89,255,.55)" },
          "100%": { boxShadow: "0 0 0 18px rgba(43,89,255,0)" },
        },
        rise: { "0%": { transform: "translateY(8px)", opacity: "0" }, "100%": { transform: "none", opacity: "1" } },
      },
      animation: {
        stamp: "stamp .45s cubic-bezier(.2,.9,.3,1.2) both",
        pulsering: "pulsering 1s ease-out 2",
        rise: "rise .2s ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
