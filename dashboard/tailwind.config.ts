import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Matching Python SLIDE_COLORS palette
        navy: {
          950: "#020617",
          900: "#0a0e1a",
          800: "#0f1629",
          700: "#1a2035",
          600: "#1e2d4a",
        },
        cyan: {
          DEFAULT: "#4FC3F7",
          glow: "rgba(79,195,247,0.15)",
          dim: "rgba(79,195,247,0.08)",
        },
      },
      fontFamily: {
        sans: ["Fira Sans", "system-ui", "sans-serif"],
        mono: ["Fira Code", "monospace"],
      },
      backdropBlur: {
        xs: "2px",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4,0,0.6,1) infinite",
        "blob": "blob 8s infinite",
        "slide-in": "slideIn 0.3s cubic-bezier(0.16,1,0.3,1)",
        "fade-in": "fadeIn 0.2s ease-out",
      },
      keyframes: {
        blob: {
          "0%,100%": { transform: "translate(0,0) scale(1)" },
          "33%": { transform: "translate(30px,-20px) scale(1.05)" },
          "66%": { transform: "translate(-20px,15px) scale(0.95)" },
        },
        slideIn: {
          from: { opacity: "0", transform: "translateX(-12px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        fadeIn: {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
      },
      boxShadow: {
        cyan: "0 0 20px rgba(79,195,247,0.15)",
        "cyan-lg": "0 0 40px rgba(79,195,247,0.2)",
        card: "0 4px 24px rgba(0,0,0,0.4)",
      },
    },
  },
  plugins: [],
};

export default config;
