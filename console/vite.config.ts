import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1200 },
  server: {
    // The console is served from the same origin as the API in production (FastAPI
    // mounts dist/), so dev proxies rather than hard-coding a host anywhere in the app.
    proxy: {
      "/api": "http://127.0.0.1:8080",
      "/health": "http://127.0.0.1:8080",
    },
  },
});
