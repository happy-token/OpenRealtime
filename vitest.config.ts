import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: {
    jsx: "automatic",
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "node",
    include: [
      "src/lib/**/*.test.ts",
      "src/hooks/**/*.test.ts",
      "src/components/**/*.test.tsx",
      "src/app/api/**/*.test.ts",
      "src/app/settings/**/*.test.tsx",
      "src/voice/**/*.test.ts",
    ],
  },
});
