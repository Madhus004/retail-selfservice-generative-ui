import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": import.meta.dirname,
    },
  },
  test: {
    environment: "jsdom",
    // Enables React Testing Library's automatic per-test DOM cleanup (it
    // registers via the global afterEach hook).
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
  },
});
