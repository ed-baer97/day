import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** Локальный просмотр против площадки. В git не входит. */
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://93.171.232.47",
      "/health": "http://93.171.232.47",
    },
  },
});
