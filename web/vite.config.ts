import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  appType: "spa",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.MODEL_FORGE_API_ORIGIN ?? "http://127.0.0.1:8765",
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 4173,
  },
});
