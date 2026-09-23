import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#f0f5ff",
          100: "#e0ebff",
          500: "#4f6ef7",
          600: "#3d56db",
          700: "#2f44b0",
        },
      },
    },
  },
  plugins: [],
};

export default config;