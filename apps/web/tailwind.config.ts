import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        airlock: {
          ink: "#0f172a",
          slate: "#1e293b",
          mist: "#f1f5f9",
          steel: "#334155",
          accent: "#0e7490",
          accentSoft: "#ecfeff",
          pass: "#15803d",
          flag: "#b45309",
          hold: "#1d4ed8",
          reject: "#b91c1c",
        },
      },
      fontFamily: {
        sans: [
          "var(--font-setup-sans)",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
        display: [
          "var(--font-setup-display)",
          "var(--font-setup-sans)",
          "sans-serif",
        ],
        mono: ["var(--font-setup-mono)", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
