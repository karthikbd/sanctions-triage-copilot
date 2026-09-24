import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Builds into the Python package (src/sanctions_copilot/webui) so FastAPI serves it everywhere: locally, in Docker
// and inside the Vercel function bundle.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../src/sanctions_copilot/webui", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
