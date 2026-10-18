import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: { DEFAULT: "#F4F1EA", 2: "#FBF9F4", 3: "#ECE7DC" },
        line: { DEFAULT: "#E2DDD1", soft: "#EEEAE1", strong: "#D3CCBC" },
        ink: { DEFAULT: "#1B1D22", 2: "#3A3D45", 3: "#4A4E57", muted: "#5B5F69" },
        accent: { DEFAULT: "#2B59FF", ink: "#1E44D6", soft: "#E4EAFF" },
        warn: { DEFAULT: "#E8590C", ink: "#8A3B0A", soft: "#FFE6D6", strong: "#B33A00" },
        ok: { DEFAULT: "#12804A", ink: "#0F4D2C", soft: "#DDF2E3" },
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
