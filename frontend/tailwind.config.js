/** @type {import('tailwindcss').Config} */
const config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          400: "#60a5fa",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
          800: "#1e40af",
          900: "#1e3a8a",
        },
        eth: {
          // Ethiopian flag palette
          dark:    "#0B3D2E",   // deep forest green
          forest:  "#1B4332",   // forest green
          mid:     "#2D6A4F",   // mid green
          bright:  "#40916C",   // bright green
          leaf:    "#078930",   // Ethiopian flag green
          mint:    "#D8F3DC",   // light mint
          mist:    "#F0FDF4",   // near-white tint
          gold:    "#FCDD09",   // Ethiopian flag yellow
          amber:   "#E6B800",   // deeper gold
          red:     "#DA121A",   // Ethiopian flag red
          crimson: "#A50E14",   // darker red
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      backgroundImage: {
        "eth-gradient": "linear-gradient(135deg, #0B3D2E 0%, #1B4332 40%, #2D6A4F 100%)",
        "eth-hero":     "linear-gradient(160deg, #0B3D2E 0%, #1B4332 60%, #2D6A4F 100%)",
        "gold-gradient":"linear-gradient(135deg, #FCDD09 0%, #E6B800 100%)",
      },
      animation: {
        "fade-in":   "fadeIn 0.5s ease-in-out",
        "slide-up":  "slideUp 0.6s ease-out",
      },
      keyframes: {
        fadeIn:  { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
        slideUp: { "0%": { opacity: "0", transform: "translateY(20px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
      },
    },
  },
  plugins: [],
};

module.exports = config;
