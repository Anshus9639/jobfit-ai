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
          50: "#f5f5f5",
          100: "#e5e5e5",
          500: "#a3a3a3",
          600: "#d4d4d4",
          700: "#f5f5f5",
        },
      },
    },
  },
  plugins: [],
};

export default config;