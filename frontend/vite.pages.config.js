import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const ghPages = process.env.GITHUB_PAGES === "true";
const viteApi = (process.env.VITE_API_BASE || "").trim();
if (ghPages && !viteApi) {
  throw new Error(
    "GitHub Actions Pages build expects VITE_API_BASE (HTTPS URL of your deployed API). " +
      "Set Actions variable VITE_API_BASE in Repo → Settings → Secrets and variables → Actions → Variables.",
  );
}

export default defineConfig({
  plugins: [react()],
  // GitHub Pages serves app from /<repo>/ path.
  base: process.env.GITHUB_PAGES
    ? `/${String(process.env.GITHUB_REPOSITORY || "").split("/").pop() || "economicCalendarr"}/`
    : "/",
});
