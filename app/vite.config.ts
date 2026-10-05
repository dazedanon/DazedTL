import { defineConfig } from "vite";
export default defineConfig({
  base: "./",
  build: {
    target: "chrome120",
    // The renderer loads from local disk, so warn only if the bundle doubles.
    chunkSizeWarningLimit: 1000,
    rolldownOptions: {
      // React Server Component directives such as "use client" have no
      // meaning in this single-page renderer.
      checks: { moduleLevelDirective: false },
    },
  },
});
