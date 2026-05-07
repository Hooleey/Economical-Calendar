import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // GitHub Pages serves app from /<repo>/ path.
  base: process.env.GITHUB_PAGES
    ? `/${String(process.env.GITHUB_REPOSITORY || "").split("/").pop() || "economicCalendarr"}/`
    : "/",
});
